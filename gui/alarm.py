"""
알림 소리 (후원 · 구독)
=======================

후원이 오면 '도-미' 두 음, 구독이 오면 '솔-도-미' 세 음으로 부드럽게 알려줘요.
(후원과 구독을 소리만 듣고도 구분할 수 있어요. 켜고 끄기도 따로예요)

- 크기(0~100%)와 음 높이(낮게 · 보통 · 높게)를 후원 소리 · 구독 소리마다 따로 맞출 수 있어요.
- 소리 파일을 따로 두지 않고, 프로그램이 직접 만들어 임시 폴더에 저장해 써요.
- 귀가 아프지 않게: 낮은 음 · 부드러운 시작(20ms) · 천천히 사라지는 끝 · 고음을 깎는 필터 · 작은 볼륨
- 윈도우 기본 소리 기능(winsound)으로 재생해요. 쓸 수 없으면 시스템 '띵' 소리로 대신해요.
- 같은 종류의 소리가 너무 붙어서 오면 건너뛰어요. (겹쳐서 지직거리지 않게)
"""

import glob
import math
import os
import struct
import tempfile
import time
import wave
from typing import Dict, List, Tuple

from PySide6.QtWidgets import QApplication

N_SAMPLE_RATE = 44100

# 소리 모양: (시작 시각 초, 높이 Hz, 길이 초) 음표들. 음표끼리 살짝 겹쳐서 이어져요.
DICT_SOUNDS: Dict[str, List[Tuple[float, float, float]]] = {
    "donation": [(0.00, 523.25, 0.34), (0.13, 659.25, 0.46)],                                   # 도 → 미
    "subscription": [(0.00, 392.00, 0.40), (0.14, 523.25, 0.40), (0.28, 659.25, 0.62)],         # 솔 → 도 → 미
    "notice": [(0.00, 587.33, 0.30), (0.16, 440.00, 0.50)],                                     # 레 → 라 (내려가는 부드러운 '주의' 소리)
}
F_PEAK_MAX = 0.60           # 크기 100% 일 때 가장 큰 소리 (0 ~ 1, 1 이 최대)
N_DEFAULT_VOLUME = 70       # 기본 크기(%). 제곱으로 줄여서 70% 가 최대 0.29 정도로 조용해요.
STR_DEFAULT_PITCH = "mid"
# 음 높이: 이름 → 배율 (낮게는 약 반음 3개 아래, 높게는 3개 위)
DICT_PITCH = {"low": 0.84, "mid": 1.0, "high": 1.19}
F_ATTACK_SEC = 0.020        # 소리가 시작될 때 서서히 커지는 시간 ('똑' 하는 날카로움을 없애요)
F_DECAY = 3.2               # 클수록 빨리 사라져요
F_HARMONIC = 0.10           # 높은 배음(소리의 날카로움) 비율
F_LOWPASS_HZ = 1800.0       # 이보다 높은 소리는 깎아요
F_MIN_INTERVAL_SEC = 0.5    # 같은 종류가 이보다 붙어서 오면 다음 소리는 건너뛰어요.
STR_TEMP_DIR = tempfile.gettempdir()


def NormalizeVolume(objValue) -> int:
    """설정에서 읽은 크기를 0 ~ 100 의 정수로 맞춰요. (이상한 값은 기본 크기)"""
    try:
        return max(0, min(100, int(objValue)))
    except (TypeError, ValueError):
        return N_DEFAULT_VOLUME


def NormalizePitch(objValue) -> str:
    return objValue if objValue in DICT_PITCH else STR_DEFAULT_PITCH


def PeakFor(nVolume: int) -> float:
    """크기(%) → 가장 큰 소리. 제곱으로 줄여서 작은 쪽을 더 세밀하게 맞출 수 있어요."""
    return F_PEAK_MAX * (NormalizeVolume(nVolume) / 100.0) ** 2


def ChimePath(strKind: str, nVolume: int = N_DEFAULT_VOLUME, strPitch: str = STR_DEFAULT_PITCH) -> str:
    # 크기 · 높이가 바뀌면 파일 이름도 바뀌어요. (재생 중인 파일을 덮어쓰다 실패하지 않게)
    return os.path.join(STR_TEMP_DIR, f"BangsongHelper_chime_{strKind}_{NormalizeVolume(nVolume)}_{NormalizePitch(strPitch)}.wav")


def BuildSamples(strKind: str, nVolume: int = N_DEFAULT_VOLUME, strPitch: str = STR_DEFAULT_PITCH) -> List[float]:
    """소리를 -1 ~ 1 사이 숫자 목록으로 만들어요."""
    fPitch = DICT_PITCH[NormalizePitch(strPitch)]
    listNotes = [(fStart, fFreq * fPitch, fLen) for fStart, fFreq, fLen in DICT_SOUNDS[strKind]]
    nTotal = int(N_SAMPLE_RATE * (max(fStart + fLen for fStart, _, fLen in listNotes) + 0.05))
    listMix = [0.0] * nTotal
    nAttack = max(1, int(N_SAMPLE_RATE * F_ATTACK_SEC))
    for fStart, fFreq, fLen in listNotes:
        nBegin, nCount = int(N_SAMPLE_RATE * fStart), int(N_SAMPLE_RATE * fLen)
        nRelease = max(1, int(N_SAMPLE_RATE * 0.06))   # 끝 60ms 는 0 으로 부드럽게
        for nIndex in range(nCount):
            fTime = nIndex / N_SAMPLE_RATE
            fAttack = 0.5 - 0.5 * math.cos(math.pi * min(1.0, nIndex / nAttack))     # 0 → 1 (부드러운 곡선)
            fRelease = min(1.0, (nCount - 1 - nIndex) / nRelease)                     # 끝에서 1 → 0
            fEnvelope = fAttack * fRelease * math.exp(-F_DECAY * nIndex / nCount)
            fWave = math.sin(2 * math.pi * fFreq * fTime) + F_HARMONIC * math.sin(4 * math.pi * fFreq * fTime)
            listMix[nBegin + nIndex] += fEnvelope * fWave
    # 높은 소리 깎기 (한 단계 저역 통과 필터)
    fRc = 2 * math.pi * F_LOWPASS_HZ
    fAlpha = fRc / (fRc + N_SAMPLE_RATE)
    fPrev = 0.0
    for nIndex, fValue in enumerate(listMix):
        fPrev += fAlpha * (fValue - fPrev)
        listMix[nIndex] = fPrev
    # 가장 큰 소리가 크기에 맞는 값이 되게 맞춰요. (음표가 몇 개든 같은 크기로 들리게)
    fMax = max(abs(fValue) for fValue in listMix) or 1.0
    fPeak = PeakFor(nVolume)
    return [fValue * fPeak / fMax for fValue in listMix]


def WriteChimeFile(strPath: str, strKind: str = "donation", nVolume: int = N_DEFAULT_VOLUME,
                   strPitch: str = STR_DEFAULT_PITCH) -> None:
    """소리를 wav 파일로 만들어요. (16비트 모노)"""
    listSamples = BuildSamples(strKind, nVolume, strPitch)
    with wave.open(strPath, "wb") as objFile:
        objFile.setnchannels(1)
        objFile.setsampwidth(2)
        objFile.setframerate(N_SAMPLE_RATE)
        objFile.writeframes(b"".join(struct.pack("<h", int(fValue * 32767)) for fValue in listSamples))


class DonationAlarm:
    """후원 · 구독 알림 소리를 내요. Play("donation") / Play("subscription")"""

    def __init__(self):
        self.dictReady: Dict[str, str] = {}       # 종류 → 이번 실행에서 만들어 둔 파일 경로
        self.dictLastPlayedAt: Dict[str, float] = {}
        self.dictStyle: Dict[str, Tuple[int, str]] = {strKind: (N_DEFAULT_VOLUME, STR_DEFAULT_PITCH) for strKind in DICT_SOUNDS}

    def SetStyle(self, strKind: str, nVolume, strPitch) -> None:
        """종류별 크기(0~100) · 음 높이(low / mid / high)를 정해요. 다음 소리부터 적용돼요."""
        if strKind in DICT_SOUNDS:
            self.dictStyle[strKind] = (NormalizeVolume(nVolume), NormalizePitch(strPitch))

    def GetStyle(self, strKind: str) -> Tuple[int, str]:
        return self.dictStyle.get(strKind, (N_DEFAULT_VOLUME, STR_DEFAULT_PITCH))

    def Prepare(self) -> None:
        """소리 파일을 미리 만들어 둬요. (첫 알림이 늦지 않게)"""
        for strKind in DICT_SOUNDS:
            self._EnsureFile(strKind)

    def _EnsureFile(self, strKind: str) -> str:
        """지금 크기 · 높이에 맞는 소리 파일을 준비하고 경로를 돌려줘요. (못 만들면 "")"""
        nVolume, strPitch = self.GetStyle(strKind)
        strPath = ChimePath(strKind, nVolume, strPitch)
        if self.dictReady.get(strKind) == strPath and os.path.exists(strPath):
            return strPath
        try:
            WriteChimeFile(strPath, strKind, nVolume, strPitch)  # 예전에 남은 파일이 있어도 새로 써요.
        except OSError:
            return ""
        self.dictReady[strKind] = strPath
        # 다른 크기 · 높이로 만들었던 예전 파일은 지워요. (재생 중이라 못 지우면 그냥 둬요)
        for strOld in glob.glob(os.path.join(STR_TEMP_DIR, f"BangsongHelper_chime_{strKind}*.wav")):
            if os.path.normcase(strOld) != os.path.normcase(strPath):
                try:
                    os.remove(strOld)
                except OSError:
                    pass
        return strPath

    def Play(self, strKind: str = "donation") -> bool:
        """소리를 내요. 돌려주는 값: 냈으면 True (너무 붙어서 건너뛰었거나 크기가 0 이면 False)"""
        if strKind not in DICT_SOUNDS:
            strKind = "donation"
        if self.GetStyle(strKind)[0] <= 0:      # 크기 0% = 무음
            return False
        fNow = time.monotonic()
        if fNow - self.dictLastPlayedAt.get(strKind, 0.0) < F_MIN_INTERVAL_SEC:
            return False
        self.dictLastPlayedAt[strKind] = fNow
        strPath = self._EnsureFile(strKind)
        if strPath:
            try:
                import winsound
                # 비동기로 재생해서 화면이 멈추지 않아요. (파일이 없을 때 나는 기본음은 끄고)
                winsound.PlaySound(strPath, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                return True
            except (ImportError, RuntimeError):
                pass
        QApplication.beep()
        return True
