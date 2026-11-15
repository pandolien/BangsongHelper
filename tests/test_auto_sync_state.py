"""auto_sync_state 규칙 시험.  실행: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_sync_state as A  # noqa: E402


def _Applied(bTemporary=False, strPrev="old", fNow=1000.0):
    objState = A.AutoSyncState(strGameId="1", strGameName="g")
    A.MarkApplied(objState, "GAME", "new", "새 게임", strPrev, bTemporary, fNow)
    return objState


class JudgeDriftTest(unittest.TestCase):
    def test_skip_without_state_or_apply(self):
        self.assertEqual(A.JudgeDrift(None, "x", 0), A.STR_DRIFT_SKIP)
        self.assertEqual(A.JudgeDrift(A.AutoSyncState(strGameId="1"), "x", 0), A.STR_DRIFT_SKIP)

    def test_skip_during_grace(self):
        objState = _Applied()
        self.assertEqual(A.JudgeDrift(objState, "old", 1000 + A.N_GRACE_SECONDS - 1), A.STR_DRIFT_SKIP)

    def test_skip_when_actual_unknown(self):
        self.assertEqual(A.JudgeDrift(_Applied(), None, 2000), A.STR_DRIFT_SKIP)

    def test_ok(self):
        self.assertEqual(A.JudgeDrift(_Applied(), "new", 2000), A.STR_DRIFT_OK)

    def test_correct_when_still_previous(self):
        self.assertEqual(A.JudgeDrift(_Applied(), "old", 2000), A.STR_DRIFT_CORRECT)

    def test_override_when_user_changed(self):
        self.assertEqual(A.JudgeDrift(_Applied(), "other", 2000), A.STR_DRIFT_OVERRIDE)

    def test_override_when_previous_unknown(self):
        self.assertEqual(A.JudgeDrift(_Applied(strPrev=None), "old", 2000), A.STR_DRIFT_OVERRIDE)

    def test_override_is_sticky(self):
        objState = _Applied()
        objState.bUserOverride = True
        self.assertEqual(A.JudgeDrift(objState, "new", 2000), A.STR_DRIFT_SKIP)

    def test_giveup_after_max_corrections(self):
        objState = _Applied()
        objState.nCorrections = A.N_MAX_CORRECTIONS
        self.assertEqual(A.JudgeDrift(objState, "old", 2000), A.STR_DRIFT_GIVEUP)

    def test_correction_keeps_previous_and_restarts_grace(self):
        objState = _Applied()
        A.MarkApplied(objState, "GAME", "new", "새 게임", "WRONG", False, 2000.0, bCorrection=True)
        self.assertEqual(objState.strPrevCategoryId, "old")
        self.assertEqual(A.JudgeDrift(objState, "old", 2010), A.STR_DRIFT_SKIP)


class RetryTest(unittest.TestCase):
    def test_confirmed_never_retries(self):
        self.assertFalse(A.IsRetryDue(_Applied(bTemporary=False), 10 ** 9))

    def test_temporary_due_after_first_interval(self):
        objState = _Applied(bTemporary=True)
        self.assertFalse(A.IsRetryDue(objState, 1000 + A.TUPLE_RETRY_SECONDS[0] - 1))
        self.assertTrue(A.IsRetryDue(objState, 1000 + A.TUPLE_RETRY_SECONDS[0]))

    def test_not_due_when_override_or_running(self):
        objState = _Applied(bTemporary=True)
        objState.bUserOverride = True
        self.assertFalse(A.IsRetryDue(objState, 10 ** 9))
        objState.bUserOverride = False
        objState.bRetrying = True
        self.assertFalse(A.IsRetryDue(objState, 10 ** 9))

    def test_gives_up_after_all_intervals(self):
        objState = _Applied(bTemporary=True)
        fNow = 1000.0
        for _ in A.TUPLE_RETRY_SECONDS:
            fNow = objState.fNextRetryAt
            self.assertTrue(A.IsRetryDue(objState, fNow))
            A.ScheduleNextRetry(objState, fNow)
        self.assertFalse(A.IsRetryDue(objState, 10 ** 12))

    def test_upgrade_to_confirmed_stops_retry(self):
        objState = _Applied(bTemporary=True)
        A.MarkApplied(objState, "GAME", "real", "진짜", "old", False, 5000.0)
        self.assertFalse(A.IsRetryDue(objState, 10 ** 12))


if __name__ == "__main__":
    unittest.main()
