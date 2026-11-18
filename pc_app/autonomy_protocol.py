"""Strict, read-only parsing and bounded USB commands for device autonomy."""
from __future__ import annotations
from dataclasses import dataclass
import re

@dataclass(frozen=True)
class ProfileStatus:
    active: int
    boot: int
    saved: tuple[bool,bool,bool]

@dataclass(frozen=True)
class AirflowStatus:
    intake_cfm: float | None
    exhaust_cfm: float | None
    balance: int | None
    valid: bool
    unknown: int
    tendency: str

@dataclass(frozen=True)
class FanAirflow:
    channel: int
    direction: int
    rated_rpm: int
    cfm10: int
    restriction: int

PROFILE_PATTERN=re.compile(r"PROFILE ACTIVE=(\d+) BOOT=(\d+) SLOTS=([01]{3})\Z")
AIRFLOW_PATTERN=re.compile(r"AIRFLOW IN10=(\d+) OUT10=(\d+) BALANCE=(-?\d+) VALID=([01]) UNKNOWN=(\d+) TREND=([\w-]+)\Z")
FAN_PATTERN=re.compile(r"AIRCFG CH=(\d+) DIR=(\d+) RPM=(\d+) CFM10=(\d+) RESTRICT=(\d+)\Z")

def parse_profile(line: str) -> ProfileStatus | None:
    match=PROFILE_PATTERN.fullmatch(line)
    if not match: return None
    active,boot=map(int,match.groups()[:2])
    saved=tuple(bit=="1" for bit in match[3])
    if active>3 or boot>3 or (active and not saved[active-1]) or (boot and not saved[boot-1]):
        return None
    return ProfileStatus(active,boot,saved) # type: ignore[arg-type]

def parse_airflow(line: str) -> AirflowStatus | None:
    match=AIRFLOW_PATTERN.fullmatch(line)
    if not match: return None
    amount_in,amount_out,balance,valid,unknown,trend=match.groups()
    tin,tout,b,un=int(amount_in),int(amount_out),int(balance),int(unknown)
    if (tin>24000 or tout>24000 or not -100<=b<=100 or un>8 or
        trend not in ("unavailable","intake-biased","exhaust-biased","balanced-estimate")):
        return None
    ok=valid=="1"
    if not ok and trend!="unavailable":
        return None
    return AirflowStatus(tin/10 if ok else None,tout/10 if ok else None,
                         b if ok else None,ok,un,trend)

def parse_fan(line: str) -> FanAirflow | None:
    match=FAN_PATTERN.fullmatch(line)
    if not match: return None
    values=tuple(map(int,match.groups()))
    if values[0] not in range(1,9) or not valid_airflow(*values[1:]):
        return None
    return FanAirflow(*values)

def valid_airflow(direction: int, rpm: int, cfm10: int, restriction: int) -> bool:
    if any(type(v) is not int for v in (direction,rpm,cfm10,restriction)):
        return False
    if direction==0:
        return rpm==0 and cfm10==0
    return (direction in (1,2) and 300<=rpm<=25000 and
            1<=cfm10<=3000 and 1<=restriction<=100)

def aircfg_command(channel: int,direction:int,rpm:int,cfm10:int,restriction:int) -> str:
    if type(channel) is not int or not 1<=channel<=8 or not valid_airflow(direction,rpm,cfm10,restriction):
        raise ValueError("Некоректні параметри вентилятора")
    return f"AIRCFG {channel} {direction} {rpm} {cfm10} {restriction}"
