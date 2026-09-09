from core.ucoa.problem_recovery import ProblemRecoveryEngine, ProblemClass

def test_recovery_prefers_automatic_strategy():
    engine=ProblemRecoveryEngine()
    decision=engine.recover({'text':'timeout'}, {ProblemClass.NETWORK:[('retry',lambda: True)]})
    assert decision.resolved is True
    assert decision.requires_human is False

def test_signup_is_human_only_after_recovery_options():
    engine=ProblemRecoveryEngine()
    decision=engine.recover({'text':'Create account'}, {})
    assert decision.problem is ProblemClass.SIGNUP
    assert decision.requires_human is True
    assert 'التسجيل' in decision.required_action

def test_credits_can_offer_human_action_without_marking_task_failed():
    engine=ProblemRecoveryEngine()
    decision=engine.recover({'text':'Insufficient credits'}, {})
    assert decision.problem is ProblemClass.CREDITS
    assert decision.requires_human is True
