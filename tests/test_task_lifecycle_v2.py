from core.ucoa.task_lifecycle_v2 import TaskLifecycle, TaskState, InterventionKind

def test_checkpoint_resume_uses_same_step():
    lifecycle=TaskLifecycle(); task=lifecycle.create('t1'); task.state=TaskState.EXECUTING; task.current_step='step-7'
    cp=lifecycle.checkpoint('t1','step-7','continue',{'screen':'saved'})
    lifecycle.require_human('t1',InterventionKind.SIGNUP,'registration required','أكمل التسجيل.',cp)
    assert task.state is TaskState.WAITING_FOR_USER
    lifecycle.resume('t1')
    assert task.state is TaskState.EXECUTING
    assert task.current_step=='step-7'

def test_revision_keeps_parent_result():
    lifecycle=TaskLifecycle(); lifecycle.create('t2')
    lifecycle.begin_revision('t2','result-1','step-3')
    task=lifecycle.tasks['t2']
    assert task.state is TaskState.REVISING
    assert task.parent_result_id=='result-1'
    assert task.revision_of_step=='step-3'
