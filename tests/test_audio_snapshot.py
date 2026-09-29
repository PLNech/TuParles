"""Live recorder snapshots use only the requested tail of a take."""

import numpy as np
import pytest

from tuparles import audio


def _recorder(*blocks):
    recorder = audio.Recorder()
    recorder._chunks = [
        np.array(block, dtype=np.int16).reshape(-1, 1) for block in blocks
    ]
    return recorder


def test_snapshot_exact_tail_across_partial_chunks():
    recorder = _recorder([0, 1, 2], [3, 4, 5, 6], [7, 8])

    np.testing.assert_array_equal(recorder.snapshot(max_samples=4), [5, 6, 7, 8])
    np.testing.assert_array_equal(recorder.snapshot(max_samples=2), [7, 8])
    np.testing.assert_array_equal(recorder.snapshot(), np.arange(9))


def test_snapshot_empty_and_short_capture():
    recorder = _recorder()
    for limit in (None, 0, 10):
        result = recorder.snapshot(max_samples=limit)
        assert result.shape == (0,)
        assert result.dtype == np.int16

    recorder = _recorder([1, 2], [3])
    np.testing.assert_array_equal(recorder.snapshot(max_samples=10), [1, 2, 3])
    np.testing.assert_array_equal(recorder.snapshot(max_samples=0), [])
    with pytest.raises(ValueError, match="non-negative"):
        recorder.snapshot(max_samples=-1)


def test_snapshot_is_a_copy_and_concatenates_outside_callback_lock(monkeypatch):
    recorder = _recorder([1, 2, 3], [4, 5])
    concatenate = np.concatenate

    def checked_concatenate(chunks):
        assert not recorder._lock.locked()
        return concatenate(chunks)

    monkeypatch.setattr(audio.np, "concatenate", checked_concatenate)
    result = recorder.snapshot(max_samples=3)
    result[0] = 99
    np.testing.assert_array_equal(recorder.snapshot(max_samples=3), [3, 4, 5])
    np.testing.assert_array_equal(recorder._chunks[0].reshape(-1), [1, 2, 3])


def test_bounded_snapshot_only_visits_window_chunks():
    class CountedChunks(list):
        visited = 0

        def __reversed__(self):
            for index in range(len(self) - 1, -1, -1):
                self.visited += 1
                yield self[index]

        def copy(self):
            raise AssertionError("bounded snapshot copied the entire chunk list")

    recorder = audio.Recorder()
    recorder._chunks = CountedChunks(
        np.array([[index]], dtype=np.int16) for index in range(1_000)
    )
    np.testing.assert_array_equal(recorder.snapshot(max_samples=3), [997, 998, 999])
    assert recorder._chunks.visited == 3
