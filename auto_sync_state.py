"""자동 카테고리 변경의 '지금 상태' 를 기억하고, 치지직에 실제로 설정된 카테고리와 어긋났는지 판단해요.

화면(Qt)과 상관없는 순수한 규칙만 모아 두었어요. (그래서 따로 시험해 볼 수 있어요)

규칙 요약
- 프로그램이 카테고리를 적용하면 '무엇을, 언제, 바꾸기 전엔 뭐였는지' 를 기억해요.
- 새로고침 때마다 치지직의 실제 카테고리를 보고 비교해요.
  · 같으면 정상.
  · 다른데 '바꾸기 전 값' 그대로면 → 적용이 안 먹힌 거예요 → 자동으로 다시 맞춰요 (게임당 최대 N번).
  · 다른데 '바꾸기 전 값' 도 아니면 → 사용자가 직접 바꾼 거예요 → 그 게임이 끝날 때까지 손대지 않아요.
- 적용한 직후 잠깐은 비교하지 않아요 (치지직 쪽 반영이 늦을 수 있어서).
- 확실하지 않은 적용(추정 / 종합 게임)은 '임시' 로 표시하고, 시간이 지난 뒤 자동으로 다시 찾아봐요.
"""

from dataclasses import dataclass
from typing import Optional

N_GRACE_SECONDS = 60          # 적용 직후 이 시간 동안은 실제 카테고리를 비교하지 않아요.
N_MAX_CORRECTIONS = 2         # 한 게임에서 자동으로 다시 맞추는 최대 횟수
TUPLE_RETRY_SECONDS = (180, 360, 720)   # 임시 카테고리를 다시 찾아보는 간격 (3분, 6분, 12분 뒤)

STR_DRIFT_SKIP = "skip"          # 비교할 수 없거나 아직 비교할 때가 아니에요.
STR_DRIFT_OK = "ok"              # 실제 카테고리가 기대한 것과 같아요.
STR_DRIFT_CORRECT = "correct"    # 적용이 안 먹혔어요 → 다시 맞춰요.
STR_DRIFT_OVERRIDE = "override"  # 사용자가 직접 바꾼 것 같아요 → 건드리지 않아요.
STR_DRIFT_GIVEUP = "giveup"      # 여러 번 다시 맞췄는데도 안 돼요 → 그만해요.


@dataclass
class AutoSyncState:
    """지금 하는 게임 하나에 대한 자동 변경 기록."""

    strGameId: str
    strGameName: str = ""
    # 프로그램이 마지막으로 (성공적으로) 적용한 카테고리 — 치지직이 알려 준 값이에요.
    strCategoryType: str = ""
    strCategoryId: str = ""
    strCategoryValue: str = ""
    bApplied: bool = False            # 적용이 성공했는지 (성공해야 비교해요)
    fAppliedAt: float = 0.0           # 적용에 성공한 시각 (time.monotonic)
    strPrevCategoryId: Optional[str] = None   # 적용하기 직전에 치지직에 설정돼 있던 카테고리
    bTemporary: bool = False          # 추정 / 종합 게임처럼 확실하지 않은 적용
    nCorrections: int = 0             # 자동으로 다시 맞춘 횟수
    bUserOverride: bool = False       # 사용자가 직접 바꿨다고 판단했어요
    nRetries: int = 0                 # 임시 카테고리를 다시 찾아본 횟수
    fNextRetryAt: float = float("inf")  # 다음에 다시 찾아볼 시각 (inf = 안 해요)
    bRetrying: bool = False           # 다시 찾는 중 (겹치지 않게)


def MarkApplied(objState: AutoSyncState, strCategoryType: str, strCategoryId: str, strCategoryValue: str,
                strPrevCategoryId: Optional[str], bTemporary: bool, fNow: float, bCorrection: bool = False) -> None:
    """적용에 성공했을 때 부르세요."""
    objState.strCategoryType = strCategoryType
    objState.strCategoryId = strCategoryId
    objState.strCategoryValue = strCategoryValue
    objState.bApplied = True
    objState.fAppliedAt = fNow
    if not bCorrection:
        # 다시 맞추는 경우엔 '원래 바꾸기 전 값' 을 그대로 둬요.
        objState.strPrevCategoryId = strPrevCategoryId
    objState.bTemporary = bTemporary
    if not bTemporary:
        objState.fNextRetryAt = float("inf")   # 확실해졌으니 다시 찾을 필요 없어요.
    elif not bCorrection:
        # 임시 적용이면 다음에 다시 찾아볼 시각을 정해요. (다시 맞추기만 한 경우엔 그대로 둬요)
        objState.fNextRetryAt = fNow + NextRetryDelay(objState.nRetries)


def NextRetryDelay(nRetries: int) -> float:
    """지금까지 nRetries 번 다시 찾아봤을 때, 다음까지 기다릴 초. 더 안 할 거면 inf."""
    if nRetries < 0 or nRetries >= len(TUPLE_RETRY_SECONDS):
        return float("inf")
    return float(TUPLE_RETRY_SECONDS[nRetries])


def JudgeDrift(objState: Optional[AutoSyncState], strActualCategoryId: Optional[str], fNow: float) -> str:
    """치지직에 실제로 설정된 카테고리를 보고, 어떻게 할지 알려줘요."""
    if objState is None or not objState.bApplied or objState.bUserOverride:
        return STR_DRIFT_SKIP
    if not strActualCategoryId:
        return STR_DRIFT_SKIP
    if fNow - objState.fAppliedAt < N_GRACE_SECONDS:
        return STR_DRIFT_SKIP
    if strActualCategoryId == objState.strCategoryId:
        return STR_DRIFT_OK
    if objState.strPrevCategoryId and strActualCategoryId == objState.strPrevCategoryId:
        # 바꾸기 전 값 그대로 → 사용자가 바꾼 게 아니라 적용이 안 먹힌 거예요.
        return STR_DRIFT_CORRECT if objState.nCorrections < N_MAX_CORRECTIONS else STR_DRIFT_GIVEUP
    return STR_DRIFT_OVERRIDE


def IsRetryDue(objState: Optional[AutoSyncState], fNow: float) -> bool:
    """임시 카테고리를 지금 다시 찾아봐야 하는지."""
    return (objState is not None and objState.bApplied and objState.bTemporary
            and not objState.bUserOverride and not objState.bRetrying
            and fNow >= objState.fNextRetryAt)


def ScheduleNextRetry(objState: AutoSyncState, fNow: float) -> None:
    """다시 찾아보기를 시작할 때 부르세요. (횟수를 올리고 다음 시각을 정해요)"""
    objState.nRetries += 1
    objState.fNextRetryAt = fNow + NextRetryDelay(objState.nRetries)
