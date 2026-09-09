from core.ucoa.task_lifecycle import HumanAction, TaskLifecycle, TaskState


def test_human_wait_creates_checkpoint_and_resumes_same_step():
    runtime = TaskLifecycle('task-1')
    runtime.snapshot.completed_steps = [0, 1, 2]
    runtime.transition(TaskState.EXECUTING, step=3)
    request = runtime.wait_for_human(
        reason='signup_required', action=HumanAction.SIGN_UP,
        title='التسجيل مطلوب', message='أنشئ الحساب ثم تابع',
        state=TaskState.WAITING_FOR_SIGNUP,
        next_action={'action': 'continue'},
    )
    assert runtime.snapshot.state == TaskState.WAITING_FOR_SIGNUP.value
    assert request.resume_from_checkpoint == runtime.snapshot.checkpoint_id
    runtime.resolve_human(request.id, {'completed': True})
    assert runtime.snapshot.state == TaskState.EXECUTING.value
    assert runtime.snapshot.current_step == 3
    assert runtime.snapshot.completed_steps == [0, 1, 2]


def test_subscription_wait_is_not_terminal_failure():
    runtime = TaskLifecycle('task-2')
    runtime.transition(TaskState.EXECUTING, step=7)
    runtime.wait_for_human(
        reason='credits_required', action=HumanAction.COMPLETE_SUBSCRIPTION,
        title='الخدمة تحتاج رصيدًا', message='أكمل الاشتراك للمتابعة',
        state=TaskState.WAITING_FOR_SUBSCRIPTION,
    )
    assert runtime.snapshot.state == TaskState.WAITING_FOR_SUBSCRIPTION.value
    assert runtime.snapshot.state != TaskState.FAILED.value


def test_revision_keeps_existing_task_identity_and_targets_steps():
    runtime = TaskLifecycle('task-3')
    runtime.complete(['artifact-1'])
    runtime.revise('كبّر النص في المشهد الثالث', [4, 4, 2])
    assert runtime.snapshot.revision_of == 'task-3'
    assert runtime.snapshot.revision_target_steps == [2, 4]
    assert runtime.snapshot.result_artifact_ids == ['artifact-1']
