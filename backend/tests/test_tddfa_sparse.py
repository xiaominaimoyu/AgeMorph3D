"""Preserve upstream coordinate-index semantics even for a mixed-vertex XYZ triplet."""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
pytest.importorskip("onnxruntime")

from agemorph3d.tddfa import TddfaResult, project_vertices  # noqa: E402


def test_sparse_projection_preserves_native_z_instead_of_silently_repairing_it():
    vertices = np.array([[1, 20, 3], [61, 80, 8]], dtype=np.float32)
    result = TddfaResult(
        shape=np.zeros(40),
        expr=np.zeros(10),
        vertices=vertices,
        triangles=np.array([[0, 1, 0]]),
        projection=np.array([[1, 0, 0.5, 0], [0, 1, 0, 0], [0, 0, 1, 0]], dtype=np.float32),
        roi=(0, 0, 120, 120),
        topology_sha256="synthetic",
    )
    coordinate_indices = np.tile([0, 1, 5], (68, 1))
    sparse = project_vertices(result, coordinate_indices)
    # x/y come from vertex 0, z from vertex 1. Projection mixes z into image x.
    np.testing.assert_allclose(sparse, np.tile([4, 100, 0], (68, 1)))
    assert project_vertices(result)[0, 0] == pytest.approx(1.5)
    np.testing.assert_array_equal(vertices, [[1, 20, 3], [61, 80, 8]])
