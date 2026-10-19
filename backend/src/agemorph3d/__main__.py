"""Run the single-process, loopback-only service."""

import uvicorn


def main() -> None:
    uvicorn.run(
        "agemorph3d.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        workers=1,
        proxy_headers=False,
        limit_concurrency=16,
        ws_max_size=2 * 1024 * 1024,
        timeout_keep_alive=5,
    )


if __name__ == "__main__":
    main()
