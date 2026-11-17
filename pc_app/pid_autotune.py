"""Conservative, *passive* PID tuning from measured PWM/RPM step responses.

Never commands a fan to change speed. A noisy or incomplete history must be
rejected; the ESP independently refuses unsafe hardware or invalid TACH.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
import time


@dataclass(frozen=True)
class PidRecommendation:
    kp_milli: int
    ki_milli: int
    kd_milli: int
    pwm_delta: float
    rpm_delta: float
    response_seconds: float
    sample_count: int

    @property
    def gains(self) -> tuple[int, int, int]:
        return self.kp_milli, self.ki_milli, self.kd_milli


def parse_pid_gains(line: str) -> tuple[int, tuple[int, int, int]]:
    if not isinstance(line, str) or len(line) > 100 or not line.startswith("PIDGAINS CH="):
        raise ValueError("Некоректна відповідь PIDGAINS")
    fields: dict[str, str] = {}
    for word in line.split()[1:]:
        if "=" not in word:
            raise ValueError("Невідомий формат PIDGAINS")
        key, val = word.split("=", 1)
        if key in fields:
            raise ValueError("Повторюване поле PIDGAINS")
        fields[key] = val
    try:
        ch = int(fields["CH"])
        kp, ki, kd = (int(fields[x]) for x in ("KP", "KI", "KD"))
    except (KeyError, ValueError) as exc:
        raise ValueError("Неповна відповідь PIDGAINS") from exc
    if not 1 <= ch <= 8 or not 5 <= kp <= 80 or not 0 <= ki <= 15 or not 0 <= kd <= 20:
        raise ValueError("Коефіцієнти PID поза допустимими межами")
    return ch, (kp, ki, kd)


def gains_command(channel: int, gains: tuple[int, int, int]) -> str:
    if type(channel) is not int or not 1 <= channel <= 8 or \
       not isinstance(gains, tuple) or len(gains) != 3 or \
       any(type(g) is not int for g in gains) or \
       not 5 <= gains[0] <= 80 or not 0 <= gains[1] <= 15 or \
       not 0 <= gains[2] <= 20:
        raise ValueError("Некоректні коефіцієнти PID")
    return f"PIDGAINS {channel} {gains[0]} {gains[1]} {gains[2]}"


def recommend_pid(
    history: list[tuple[float, int, int, float]],
    *,
    now: float | None = None,
) -> PidRecommendation:
    """Require two adjacent stable plateaus around a clear, correctly signed step.

    History rows come from status time/PWM/RPM/temperature. A fresh, positive
    TACH signal is required. If the evidence is insufficient, refuse to fit.
    """
    if not isinstance(history, list) or len(history) < 8:
        raise ValueError("Недостатньо телеметрії PWM/RPM (потрібен виміряний стрибок)")
    if now is None:
        now = time.time()
    if not math.isfinite(now):
        raise ValueError("Некоректний час телеметрії")
    values = history[-160:]
    if now - values[-1][0] > 120 or now < values[-1][0] - 10:
        raise ValueError("Історія RPM застаріла")
    segments: list[list[tuple[float, int, int]]] = []
    last_time = float("-inf")
    for stamp, pwm, rpm, temp in values:
        if (not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in (stamp, pwm, rpm, temp)) or
            stamp <= last_time):
            raise ValueError("Некоректна або неупорядкована телеметрія")
        last_time = stamp
        if not (15 <= pwm <= 100 and 200 <= rpm <= 25000 and 5 <= temp <= 125):
            segments.append([])
            continue
        if not segments or not segments[-1] or abs(pwm - median(x[1] for x in segments[-1])) > 2:
            segments.append([])
        segments[-1].append((float(stamp), int(pwm), int(rpm)))

    def stable(segment: list[tuple[float, int, int]]) -> bool:
        if len(segment) < 4 or not 6 <= segment[-1][0] - segment[0][0] <= 300:
            return False
        middle = median(x[2] for x in segment[-3:])
        return max(abs(x[2] - middle) for x in segment[-3:]) <= max(60, 0.10 * middle)

    for pre, post in reversed(list(zip(segments, segments[1:]))):
        if not stable(pre) or not stable(post):
            continue
        old_pwm, new_pwm = median(x[1] for x in pre), median(x[1] for x in post)
        delta_pwm = new_pwm - old_pwm
        rpm_before = median(x[2] for x in pre[-3:])
        rpm_after = median(x[2] for x in post[-3:])
        delta_rpm = rpm_after - rpm_before
        if (abs(delta_pwm) < 10 or abs(delta_rpm) < 120 or
            delta_pwm * delta_rpm <= 0):
            continue
        motor_gain = abs(delta_rpm / delta_pwm)
        if not 5 <= motor_gain <= 160:
            continue
        crossing = rpm_before + 0.632 * delta_rpm
        reached = next((x for x in post if
                        (x[2] >= crossing if delta_rpm > 0 else x[2] <= crossing)),
                       None)
        if reached is None:
            continue
        response = max(2.0, min(20.0, reached[0] - post[0][0]))
        # Conservative bounded feedback. No live system identification:
        # gain is intentionally below aggressive IMC/ZN tuning.
        kp = max(8, min(40, round(400.0 / motor_gain)))
        ki = max(0, min(6, round(kp / (4.0 * response))))
        kd = max(0, min(8, round(kp * response * 0.012)))
        return PidRecommendation(kp, ki, kd, delta_pwm, delta_rpm,
                                 round(response, 2), len(pre) + len(post))
    raise ValueError(
        "Немає двох стабільних ділянок PWM з достовірною реакцією RPM. "
        "Потрібна зафіксована на перевіреному стенді реакція, без аварій."
    )
