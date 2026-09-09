from core.ucoa.problem_recovery import ProblemClass, ProblemRecovery, RecoveryResult
from core.ucoa.result_revision import ResultRevisionPlanner


def test_recovery_prefers_automatic_solution_before_human():
    r=ProblemRecovery()
    assert r.decide(ProblemClass.TRANSIENT).result == RecoveryResult.RETRY
    assert r.decide(ProblemClass.BLOCKING_UI,skip_available=True).result == RecoveryResult.SOLVED
    assert r.decide(ProblemClass.CREDITS,alternative_available=True).result == RecoveryResult.ALTERNATIVE
    assert r.decide(ProblemClass.CREDITS,alternative_available=False).result == RecoveryResult.HUMAN


def test_revision_targets_existing_steps_and_reuses_artifacts():
    plan=ResultRevisionPlanner().plan('كبّر النص وغيّر اللون',8)
    assert plan.target_steps
    assert plan.reuse_artifacts is True
    assert plan.estimated_new_steps <= len(plan.target_steps)
