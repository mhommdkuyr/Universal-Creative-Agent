from __future__ import annotations

from dataclasses import dataclass
import os, shutil, subprocess
from .models import Action


@dataclass
class CoreOperationsAdapter:
    name: str = "core"

    CORE_ACTIONS = {
        "ingest_reference", "analyze_reference", "inspect_target_project", "map_assets",
        "build_edit_plan", "repair_deviations", "observe", "verify_against_reference",
        "visual_verify", "verify_output", "finish", "render_preview", "render_final",
    }

    def supports(self, action: Action) -> bool:
        return action.type in self.CORE_ACTIONS

    def execute(self, action: Action):
        return {"status": "delegated", "action": action.type}


class UniversalStubAdapter:
    name='universal-stub'
    def supports(self, action): return True
    def execute(self, action): return {'status':'simulated','action':action.type,'target':action.target}


@dataclass
class BrowserUseAdapter:
    executable: str=os.getenv('BROWSER_USE_BIN','browser-use')
    name: str='browser-use'
    def supports(self, action):
        return action.type.startswith('web_') or action.type=='browser_task' or action.type in {'open_browser','execute_web_actions','verify_web_state'}
    def execute(self, action):
        if shutil.which(self.executable) is None:
            return {'status':'unavailable','reason':f'{self.executable} not installed','action':action.type}
        return {'status':'ready','executable':self.executable,'task':action.args.get('task') or action.args.get('instruction')}


@dataclass
class OpenHandsAdapter:
    name: str='openhands'
    def supports(self, action): return action.type in {'inspect_repository','plan_changes','implement','run_tests','browser_verify','fix_failures','deliver'}
    def execute(self, action):
        return {'status':'bridge_ready','adapter':self.name,'action':action.type,'workspace':action.args.get('workspace',os.getcwd())}


@dataclass
class AndroidIntentAdapter:
    name: str='android-intent'
    def supports(self, action): return action.type in {'tap','swipe','long_press','type_text','click_text','back','home','open_app','android_task','execute_target_app'}
    def execute(self, action): return {'status':'queued','channel':'android','action':action.type,'args':action.args}


@dataclass
class FFmpegAdapter:
    name: str='ffmpeg'
    def supports(self, action): return action.type in {'render_preview','render_final'} and shutil.which('ffmpeg') is not None
    def execute(self, action):
        command=action.args.get('command')
        if not command:
            return {'status':'ready','ffmpeg':shutil.which('ffmpeg'),'mode':action.type}
        if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
            return {'status':'error','reason':'command must be a list of strings'}
        p=subprocess.run(command,check=False,capture_output=True,text=True)
        return {'status':'completed' if p.returncode == 0 else 'failed','returncode':p.returncode,'stdout':p.stdout[-2000:],'stderr':p.stderr[-2000:]}
