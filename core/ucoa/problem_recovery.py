from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

class ProblemClass(str, Enum):
    TRANSIENT='transient'; UI_CHANGED='ui_changed'; NETWORK='network'; BLOCKING_AD='blocking_ad'; AUTH='auth'; SIGNUP='signup'; VERIFICATION='verification'; CREDITS='credits'; SUBSCRIPTION='subscription'; PERMISSION='permission'; UNKNOWN='unknown'

@dataclass
class RecoveryAttempt:
    strategy:str; success:bool=False; detail:str=''

@dataclass
class RecoveryDecision:
    problem:ProblemClass; resolved:bool; requires_human:bool=False; required_action:str|None=None; attempts:list[RecoveryAttempt]=field(default_factory=list)

class ProblemRecoveryEngine:
    def __init__(self, max_attempts:int=4): self.max_attempts=max_attempts
    def classify(self, observation:dict[str,Any])->ProblemClass:
        t=' '.join(str(observation.get(k,'')) for k in ('title','text','error','url')).lower()
        if any(x in t for x in ('sign up','signup','create account','إنشاء حساب')): return ProblemClass.SIGNUP
        if any(x in t for x in ('verification code','verify email','رمز التحقق')): return ProblemClass.VERIFICATION
        if any(x in t for x in ('subscribe','subscription','اشتراك')): return ProblemClass.SUBSCRIPTION
        if any(x in t for x in ('insufficient credits','out of credits','no credits','نفاد الرصيد')): return ProblemClass.CREDITS
        if any(x in t for x in ('permission','allow','صلاحية','إذن')): return ProblemClass.PERMISSION
        if any(x in t for x in ('login','sign in','تسجيل الدخول')): return ProblemClass.AUTH
        if any(x in t for x in ('skip ad','close ad','advertisement','إعلان')): return ProblemClass.BLOCKING_AD
        if any(x in t for x in ('timeout','temporarily','network','اتصال')): return ProblemClass.NETWORK
        return ProblemClass.UI_CHANGED if observation.get('ui_changed') else ProblemClass.UNKNOWN
    def recover(self, observation:dict[str,Any], strategies:dict[ProblemClass,list[tuple[str,Callable[[],bool]]]])->RecoveryDecision:
        problem=self.classify(observation); attempts=[]
        for name,fn in strategies.get(problem,[]):
            if len(attempts)>=self.max_attempts: break
            try:
                ok=bool(fn()); detail=''
            except Exception as exc:
                ok=False; detail=type(exc).__name__
            attempts.append(RecoveryAttempt(name,ok,detail))
            if ok: return RecoveryDecision(problem,True,False,attempts=attempts)
        human={ProblemClass.SIGNUP:'أكمل التسجيل في الخدمة.',ProblemClass.VERIFICATION:'أدخل رمز التحقق أو أكمل التحقق.',ProblemClass.SUBSCRIPTION:'أكمل الاشتراك في الخدمة.',ProblemClass.CREDITS:'جدّد رصيد الخدمة أو اختر خدمة بديلة.',ProblemClass.AUTH:'سجّل الدخول إلى الخدمة.',ProblemClass.PERMISSION:'امنح الإذن المطلوب إذا كنت توافق.'}
        if problem in human: return RecoveryDecision(problem,False,True,human[problem],attempts)
        return RecoveryDecision(problem,False,False,attempts=attempts)

class RecoveryResult(str, Enum):
    RETRY='retry'; SOLVED='solved'; ALTERNATIVE='alternative'; HUMAN='human'; FAILED='failed'

@dataclass(frozen=True)
class RecoveryChoice:
    result: RecoveryResult
    reason: str = ''

class ProblemRecovery:
    """Compatibility facade used by policy tests and higher-level orchestration."""
    def decide(self, problem: ProblemClass, *, skip_available: bool=False, alternative_available: bool=False) -> RecoveryChoice:
        if problem in {ProblemClass.TRANSIENT, ProblemClass.NETWORK, ProblemClass.UI_CHANGED}:
            return RecoveryChoice(RecoveryResult.RETRY, 'retryable problem')
        if problem == ProblemClass.BLOCKING_AD:
            return RecoveryChoice(RecoveryResult.SOLVED if skip_available else RecoveryResult.RETRY, 'skip or wait for blocking UI')
        if problem in {ProblemClass.CREDITS, ProblemClass.SUBSCRIPTION}:
            return RecoveryChoice(RecoveryResult.ALTERNATIVE if alternative_available else RecoveryResult.HUMAN, 'alternative or human intervention')
        if problem in {ProblemClass.AUTH, ProblemClass.SIGNUP, ProblemClass.VERIFICATION, ProblemClass.PERMISSION}:
            return RecoveryChoice(RecoveryResult.HUMAN, 'human-only security or account action')
        return RecoveryChoice(RecoveryResult.FAILED, 'no safe automatic strategy')
