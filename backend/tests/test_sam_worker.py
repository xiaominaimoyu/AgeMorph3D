"""Exercise actual synthetic subprocess ownership, frames and device leases."""

import asyncio
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import agemorph3d.sam_worker as worker_module
import pytest
from agemorph3d.aging_sessions import (
    AgingCoordinator,
    AgingSessionCache,
    SessionCapacityError,
    SessionSource,
)
from agemorph3d.errors import ApiError
from agemorph3d.sam_worker import MAX_STDERR_BYTES, SamWorkerClient, SamWorkerError
from PIL import Image


@pytest.fixture
def aligned_png():
    destination = io.BytesIO()
    Image.new("RGB", (256, 256), (80, 90, 100)).save(destination, format="PNG")
    return destination.getvalue()


@pytest.fixture
def make_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_module, "_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(worker_module, "_DEVICE_LOCK_PATH", tmp_path / "cache/sam-cuda-0.lock")
    counter = 0

    def make(config=None, **options):
        nonlocal counter
        counter += 1
        folder = tmp_path / str(counter)
        folder.mkdir()
        script = folder / "synthetic_sam_worker.py"
        shutil.copyfile(Path(__file__).parent / "fixtures/synthetic_sam_worker.py", script)
        (folder / "fake-sam-config.json").write_text(json.dumps(config or {}))
        return SamWorkerClient(
            python_executable=sys.executable,
            worker_script=script,
            manifest_path=folder / "manifest.json",
            sam_root=folder,
            research_allow_unresolved=True,
            startup_timeout_s=options.pop("startup_timeout_s", 3),
            request_timeout_s=options.pop("request_timeout_s", 2),
            shutdown_timeout_s=options.pop("shutdown_timeout_s", 1),
            **options,
        )

    return make


async def wait_idle(client):
    await asyncio.wait_for(client.wait_idle(), 2)


async def test_real_subprocess_stays_loaded_for_two_requests(make_worker, aligned_png):
    client = make_worker()
    try:
        ready = await client.start()
        assert ready["state"] == "research_loaded"
        assert ready["service_ready"] is False
        assert (await client.health())["pid"] == ready["pid"]
        first = await client.generate(aligned_png, 45)
        second = await client.generate(aligned_png, 45)
        assert first.pid == second.pid == ready["pid"]
        assert first.load_count == second.load_count == 1
        assert first.png == second.png
        assert first.sha256 == second.sha256
        assert first.input_sha256 == second.input_sha256
        with Image.open(io.BytesIO(first.png)) as image:
            assert image.size == (1024, 1024)
    finally:
        closed = await client.close()
    assert closed["returncode"] == 0
    assert closed["closed"] is True
    assert closed["forced_termination"] is False


async def test_timeout_keeps_slot_and_cuda_lease_until_actual_reply(make_worker, aligned_png):
    client = make_worker({"generate_delay": 0.25})
    contender = make_worker()
    try:
        await client.start()
        with pytest.raises(SamWorkerError) as caught:
            await client.generate(aligned_png, 45, timeout_s=0.02)
        assert caught.value.code == "TIMEOUT"
        assert client.busy
        with pytest.raises(SamWorkerError) as caught:
            await client.generate(aligned_png, 46)
        assert caught.value.code == "BUSY"
        with pytest.raises(SamWorkerError) as caught:
            await contender.start()
        assert caught.value.code == "BUSY"
        await wait_idle(client)
        assert (await client.generate(aligned_png, 46)).target_age == 46
    finally:
        await client.close()
        await contender.close()


async def test_cancelled_waiter_does_not_cancel_native_work(make_worker, aligned_png):
    client = make_worker({"generate_delay": 0.25})
    try:
        await client.start()
        task = asyncio.create_task(client.generate(aligned_png, 45))
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.busy
        with pytest.raises(SamWorkerError) as caught:
            await client.health()
        assert caught.value.code == "BUSY"
        await wait_idle(client)
        assert (await client.health())["load_count"] == 1
    finally:
        await client.close()


async def test_close_drains_active_request_and_releases_device_only_after_exit(
    make_worker, aligned_png
):
    client = make_worker({"generate_delay": 0.2})
    await client.start()
    task = asyncio.create_task(client.generate(aligned_png, 45))
    await asyncio.sleep(0.02)
    closing = asyncio.create_task(client.close())
    await asyncio.sleep(0.02)
    assert not closing.done()
    assert client.snapshot()["returncode"] is None
    with pytest.raises(SamWorkerError) as caught:
        await client.generate(aligned_png, 46)
    assert caught.value.code == "WORKER_CLOSED"
    await task
    assert (await closing)["returncode"] == 0
    replacement = make_worker()
    try:
        assert (await replacement.start())["state"] == "research_loaded"
    finally:
        await replacement.close()


async def test_cancelled_close_waiter_still_finishes_cleanup(make_worker, aligned_png):
    client = make_worker({"generate_delay": 0.2})
    await client.start()
    work = asyncio.create_task(client.generate(aligned_png, 45))
    await asyncio.sleep(0.02)
    closing = asyncio.create_task(client.close())
    await asyncio.sleep(0.02)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await work
    assert (await client.close())["returncode"] == 0


async def test_close_terminates_hung_child_then_waits_for_exit(make_worker, aligned_png):
    client = make_worker({"hang_generate": True}, shutdown_timeout_s=0.05)
    await client.start()
    with pytest.raises(SamWorkerError):
        await client.generate(aligned_png, 45, timeout_s=0.02)
    closed = await client.close()
    assert closed["returncode"] is not None
    assert closed["forced_termination"] is True
    assert not client.busy
    replacement = make_worker()
    try:
        await replacement.start()
    finally:
        await replacement.close()


async def test_cpu_worker_does_not_take_cuda_lease(make_worker):
    gpu, cpu = make_worker(), make_worker(device="cpu")
    try:
        await gpu.start()
        await cpu.start()
        assert gpu.snapshot()["pid"] != cpu.snapshot()["pid"]
    finally:
        await gpu.close()
        await cpu.close()


async def test_stderr_is_drained_and_bounded_even_before_ready(make_worker):
    client = make_worker({"stderr_bytes": 400000})
    try:
        await client.start()
    finally:
        closed = await client.close()
    assert len(closed["stderr_tail"].encode()) == MAX_STDERR_BYTES
    assert closed["returncode"] == 0


@pytest.mark.parametrize("mode", ["bad_selftest", "huge_startup", "startup_error"])
async def test_invalid_startup_closes_owned_process_and_releases_lease(make_worker, mode):
    client = make_worker({mode: True})
    with pytest.raises(SamWorkerError):
        await client.start()
    closed = await client.close()
    assert closed["returncode"] is not None
    replacement = make_worker()
    try:
        await replacement.start()
    finally:
        await replacement.close()


async def test_startup_timeout_waits_for_process_exit(make_worker):
    client = make_worker({"startup_delay": 60}, startup_timeout_s=0.03, shutdown_timeout_s=0.03)
    with pytest.raises(SamWorkerError) as caught:
        await client.start()
    assert caught.value.code == "TIMEOUT"
    assert client.snapshot()["returncode"] is not None
    assert client.snapshot()["closed"] is True


@pytest.mark.parametrize(
    "mode",
    ["wrong_id", "bad_hash", "bad_png", "bad_frame", "exit_generate", "bad_seconds", "bad_age"],
)
async def test_broken_reply_retires_process_before_releasing_slot(make_worker, aligned_png, mode):
    client = make_worker({mode: True})
    try:
        with pytest.raises(SamWorkerError) as caught:
            await client.generate(aligned_png, 45)
        assert caught.value.code in {"WORKER_PROTOCOL", "WORKER_FAILED"}
        assert client.snapshot()["returncode"] is not None, (caught.value, client.snapshot())
        assert client.snapshot()["broken"] is True
    finally:
        await client.close()


async def test_fatal_model_error_waits_for_actual_process_exit(make_worker, aligned_png):
    client = make_worker({"fatal_generate": True})
    try:
        with pytest.raises(SamWorkerError) as caught:
            await client.generate(aligned_png, 45)
        assert caught.value.code == "MODEL_INFERENCE_FAILED"
        assert client.snapshot()["returncode"] is not None
        assert not client.busy
    finally:
        await client.close()


async def test_nonfatal_validation_error_keeps_model_available(make_worker, aligned_png):
    client = make_worker({"invalid_once": True})
    try:
        with pytest.raises(SamWorkerError) as caught:
            await client.generate(aligned_png, 45)
        assert caught.value.code == "INVALID_REQUEST"
        assert (await client.generate(aligned_png, 46)).load_count == 1
    finally:
        await client.close()


@pytest.mark.parametrize("age", [19, 71, 42.5, 45.0, True, None])
async def test_age_rejection_precedes_process_launch(make_worker, aligned_png, age):
    client = make_worker()
    with pytest.raises(SamWorkerError) as caught:
        await client.generate(aligned_png, age)
    assert caught.value.code == "INVALID_REQUEST"
    assert client.snapshot()["pid"] is None
    await client.close()


@pytest.mark.parametrize("data", [b"not PNG", b"x" * (1024**2 + 1)], ids=["bad-png", "oversized"])
async def test_input_budget_rejection_precedes_process_launch(make_worker, data):
    client = make_worker()
    with pytest.raises(SamWorkerError) as caught:
        await client.generate(data, 45)
    assert caught.value.code == "INVALID_REQUEST"
    assert client.snapshot()["pid"] is None
    await client.close()


def test_device_lease_excludes_another_process(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_module, "_WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(worker_module, "_DEVICE_LOCK_PATH", tmp_path / "sam.lock")
    code = (
        "import sys; from pathlib import Path; import agemorph3d.sam_worker as m; "
        "m._WORKSPACE_ROOT=Path(sys.argv[1]); m._DEVICE_LOCK_PATH=m._WORKSPACE_ROOT/'sam.lock'; "
        "lease=m._DeviceLease(); lease.close()"
    )
    lease = worker_module._DeviceLease()
    try:
        blocked = subprocess.run(
            [sys.executable, "-B", "-c", code, str(tmp_path)], capture_output=True, timeout=5
        )
        assert blocked.returncode != 0
        assert b"SamWorkerError" in blocked.stderr
    finally:
        lease.close()
    available = subprocess.run(
        [sys.executable, "-B", "-c", code, str(tmp_path)], capture_output=True, timeout=5
    )
    assert available.returncode == 0, available.stderr
    assert (tmp_path / "sam.lock").read_bytes() == b"\0"


@pytest.fixture
def synthetic_assets(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[2] / "tools/sam_worker.py"
    spec = importlib.util.spec_from_file_location("synthetic_sam_worker_asset_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root, model_dir = tmp_path / "sam", tmp_path / "model"
    root.mkdir()
    model_dir.mkdir()
    checkpoint = model_dir / "synthetic-checkpoint.bin"
    checkpoint.write_bytes(b"synthetic model pin fixture; never unpickled")
    checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "CHECKPOINT_SHA256", checkpoint_hash)
    monkeypatch.setattr(module, "CHECKPOINT_BYTES", checkpoint.stat().st_size)
    pins = {}
    for relative in module.CODE_PINS:
        code = root / relative
        code.parent.mkdir(parents=True, exist_ok=True)
        code.write_text("# synthetic pin fixture; not executable model code\n")
        pins[relative] = hashlib.sha256(code.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "CODE_PINS", pins)
    marker = {
        "sam_commit": module.SAM_REVISION,
        "files": {
            name: {"installed_sha256": pins["models/stylegan2/op/" + name]}
            for name in ("fused_act.py", "upfirdn2d.py")
        },
    }
    (root / "models/stylegan2/op/NATIVE_OPS.json").write_text(json.dumps(marker))
    manifest_data = {
        "schema_version": 1,
        "model_id": "sam-ffhq-aging",
        "source": {"code_revision": module.SAM_REVISION},
        "license": {"status": "research-only-unresolved"},
        "artifacts": [
            {
                "path": checkpoint.name,
                "role": "aging_generator_checkpoint",
                "sha256": checkpoint_hash,
                "size_bytes": checkpoint.stat().st_size,
            }
        ],
    }
    manifest = model_dir / "manifest.json"
    manifest.write_text(json.dumps(manifest_data))
    return module, root, manifest, checkpoint


def test_research_permission_is_required_before_checkpoint_loading(synthetic_assets):
    module, root, manifest, _ = synthetic_assets
    with pytest.raises(module.ResearchWorkerError) as caught:
        module.verify_assets(manifest, root, allow_unresolved=False)
    assert caught.value.code == "ASSET_LICENSE"


def test_small_synthetic_pins_validate_without_model_loading(synthetic_assets):
    module, root, manifest, checkpoint = synthetic_assets
    evidence = module.verify_assets(manifest, root, allow_unresolved=True)
    assert evidence["checkpoint_path"] == str(checkpoint)
    assert evidence["checkpoint_sha256"] == module.CHECKPOINT_SHA256
    assert evidence["license_status"] == "research-only-unresolved"


@pytest.mark.parametrize("tamper", ["checkpoint", "shim", "marker", "revision", "escape"])
def test_asset_tampering_is_rejected_before_any_model_load(synthetic_assets, tamper):
    module, root, manifest, checkpoint = synthetic_assets
    if tamper == "checkpoint":
        checkpoint.write_bytes(b"x" * checkpoint.stat().st_size)
    elif tamper == "shim":
        (root / "models/stylegan2/op/fused_act.py").write_text("# tampered fixture\n")
    elif tamper == "marker":
        marker = root / "models/stylegan2/op/NATIVE_OPS.json"
        data = json.loads(marker.read_text())
        data["files"]["fused_act.py"]["installed_sha256"] = "0" * 64
        marker.write_text(json.dumps(data))
    else:
        data = json.loads(manifest.read_text())
        if tamper == "revision":
            data["source"]["code_revision"] = "unrecognized"
        else:
            outside = manifest.parent.parent / "outside.bin"
            shutil.copyfile(checkpoint, outside)
            data["artifacts"][0]["path"] = "../outside.bin"
        manifest.write_text(json.dumps(data))
    with pytest.raises(module.ResearchWorkerError) as caught:
        module.verify_assets(manifest, root, allow_unresolved=True)
    assert caught.value.code == "ASSET_HASH"


async def test_cancelled_drain_waiter_keeps_context_until_native_completion(
    make_worker, aligned_png
):
    client = make_worker({"generate_delay": 0.2})
    await client.start()
    with pytest.raises(SamWorkerError):
        await client.generate(aligned_png, 45, timeout_s=0.01)
    released = asyncio.Event()

    async def hold_context():
        try:
            await client.wait_idle()
        finally:
            released.set()

    task = asyncio.create_task(hold_context())
    await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.sleep(0.02)
    assert not released.is_set()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        assert released.is_set()
        assert not client.busy
    finally:
        await client.close()


@pytest.mark.parametrize("abandon", ["timeout", "cancel"])
async def test_coordinator_keeps_pin_and_admission_across_worker_timeout(
    make_worker, aligned_png, abandon
):
    client = make_worker({"generate_delay": 0.25})
    source = SessionSource(
        b'{"value":35,"method":"user","calibration_id":null}',
        b"synthetic-original-rgb-contract",
        aligned_png,
        b"synthetic-correspondence",
        b"synthetic-glb-contract",
        b"synthetic-texture-contract",
        (0.0,),
    )
    clock = [0.0]
    cache = AgingSessionCache(max_entries=1, ttl_seconds=1, clock=lambda: clock[0])
    session_id = cache.publish(source)

    async def processor(context, age):
        try:
            await client.generate(context.aligned_png, age, timeout_s=0.01)
            raise AssertionError("The synthetic worker must exceed its client timeout.")
        finally:
            await client.wait_idle()

    coordinator = AgingCoordinator(cache, processor)
    try:
        await client.start()
        task = asyncio.create_task(coordinator.generate(session_id, 45, timeout_seconds=0.04))
        if abandon == "cancel":
            await asyncio.sleep(0.025)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(ApiError) as caught:
                await task
            assert caught.value.code == "TIMEOUT"
        assert cache.stats["pins"] == 1
        assert cache.stats["results"] == 0
        with pytest.raises(ApiError) as caught:
            await coordinator.generate(session_id, 46)
        assert caught.value.code == "BUSY"
        clock[0] = 2
        with pytest.raises(SessionCapacityError):
            cache.publish(source)
        await coordinator.close()
        assert cache.stats["pins"] == 0
        assert cache.stats["entries"] == 0
    finally:
        await coordinator.close()
        await client.close()
