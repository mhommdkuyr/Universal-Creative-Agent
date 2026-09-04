from .models import Plan, TaskSpec, Action

class CreativePlanner:
    def plan(self, task: TaskSpec, route: str) -> Plan:
        if route == "creative_replication":
            actions = [
                Action("ingest_reference", args={"uri": task.reference.source if task.reference else None}),
                Action("analyze_reference", args={"modalities": ["audio", "visual", "text", "timing", "style"]}),
                Action("inspect_target_project", args={"project": task.constraints.get("project_id", "20")}),
                Action("map_assets", args={"policy": "reuse_user_assets"}),
                Action("build_edit_plan", args={"fidelity": task.constraints.get("fidelity", "high")}),
                Action("execute_target_app", target=task.target, args={"mode": "gui_plus_native"}),
                Action("render_preview"),
                Action("verify_against_reference", args={"threshold": task.constraints.get("threshold", 0.90)}),
                Action("repair_deviations", args={"max_passes": 3}),
                Action("render_final"),
            ]
        elif route == "creative_editing":
            actions = [Action("open_target", target=task.target), Action("execute_edit_plan"), Action("verify_output"), Action("render_final")]
        elif route == "creative_design":
            actions = [Action("analyze_reference_or_prompt"), Action("open_design_target", target=task.target), Action("build_design"), Action("visual_verify"), Action("export")]
        elif route == "software_engineering":
            actions = [Action("inspect_repository"), Action("plan_changes"), Action("implement"), Action("run_tests"), Action("browser_verify"), Action("fix_failures"), Action("deliver")]
        elif route == "browser_automation":
            actions = [Action("open_browser"), Action("observe"), Action("execute_web_actions"), Action("verify_web_state"), Action("finish")]
        else:
            actions = [Action("observe"), Action("reason"), Action("act"), Action("verify")]
        checkpoints = [{"after": a.type, "required": a.type.startswith("verify") or a.type in {"render_preview", "render_final"}} for a in actions]
        return Plan(task_id=task.id, strategy=route, actions=actions, checkpoints=checkpoints)
