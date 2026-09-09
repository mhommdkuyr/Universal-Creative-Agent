from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

class ProblemClass(str, Enum):
    TRANSIENT='transient'; BLOCKING_UI='blocking_ui'; SIGNUP='signup'; VERIFICATION='verification'; CREDITS='credits'; SUBSCRIPTION='subscription'; PERMISSION='permission'; UNKNOWN='unknown'

class RecoveryResult(str, Enum):
    SOLVED='solved'; RETRY='retry'; ALTERNATIVE='alternative'; HUMAN='human'; TERMINAL='terminal'

@dataclass
class RecoveryDecision:
    problem:ProblemClass
    result:RecoveryResult
    message:str
    human_action:Optional[str]=None
    retry_after_ms:int=0
    alternatives:List[Dict[str,Any]]=None

class ProblemRecovery:
    """Policy-first recovery. Human intervention is a last resort, never the first response."""
    def classify(self, text:str, *, skip_available=False, login_required=False, signup_required=False, credits_required=False, subscription_required=False, permission_required=False)->ProblemClass:
        if signup_required:return ProblemClass.SIGNUP
        if login_required:return ProblemClass.VERIFICATION
        if subscription_required:return ProblemClass.SUBSCRIPTION
        if credits_required:return ProblemClass.CREDITS
        if permission_required:return ProblemClass.PERMISSION
        if skip_available:return ProblemClass.BLOCKING_UI
        t=(text or '').lower()
        if any(x in t for x in ('timeout','timed out','انتهت المهلة','network','شبكة','try again','حاول مرة أخرى')):return ProblemClass.TRANSIENT
        return ProblemClass.UNKNOWN
    def decide(self, problem:ProblemClass, *, skip_available=False, alternative_available=False)->RecoveryDecision:
        if problem==ProblemClass.BLOCKING_UI and skip_available:return RecoveryDecision(problem,RecoveryResult.SOLVED,'إغلاق أو تخطي النافذة ثم متابعة المهمة.')
        if problem==ProblemClass.TRANSIENT:return RecoveryDecision(problem,RecoveryResult.RETRY,'إعادة المحاولة بعد إعادة الملاحظة.',retry_after_ms=1200)
        if problem==ProblemClass.CREDITS and alternative_available:return RecoveryDecision(problem,RecoveryResult.ALTERNATIVE,'البحث عن خدمة بديلة قبل طلب تدخل المستخدم.')
        human={ProblemClass.SIGNUP:('التسجيل بنفسي','إنشاء الحساب ثم متابعة المهمة.'),ProblemClass.VERIFICATION:('إدخال رمز التحقق','إكمال التحقق ثم متابعة المهمة.'),ProblemClass.SUBSCRIPTION:('إكمال الاشتراك','إكمال الاشتراك ثم متابعة المهمة.'),ProblemClass.PERMISSION:('منح الإذن','منح الإذن المطلوب فقط ثم متابعة المهمة.'),ProblemClass.CREDITS:('إكمال الاشتراك','لم يبقَ حل آلي متاح؛ يمكن إكمال الاشتراك ثم استئناف المهمة.')}
        if problem in human:
            action,msg=human[problem]; return RecoveryDecision(problem,RecoveryResult.HUMAN,msg,human_action=action)
        if alternative_available:return RecoveryDecision(problem,RecoveryResult.ALTERNATIVE,'إعادة التخطيط باستخدام بديل متاح.')
        return RecoveryDecision(problem,RecoveryResult.TERMINAL,'لم يتوفر حل آلي أو بديل آمن بعد استنفاد محاولات الإصلاح.')
