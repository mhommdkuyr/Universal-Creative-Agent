from .models import TaskSpec

class TaskRouter:
    def route(self, task: TaskSpec) -> str:
        t = task.intent.lower()
        ref_video = task.reference and task.reference.media_type == "video"
        ref_image = task.reference and task.reference.media_type == "image"
        replication_words = ("مثل", "مشابه", "replicate", "reference", "نفس", "انسخ", "أسلوب", "قلده", "مطابق", "copy", "recreate")
        if (ref_video or ref_image) and any(k in t for k in replication_words):
            return "creative_replication"
        if any(k in t for k in ("capcut", "premiere", "davinci", "video", "مونتاج", "فيديو", "تحرير الفيديو")):
            return "creative_editing"
        if any(k in t for k in ("canva", "figma", "photoshop", "صمم", "تصميم", "صورة", "poster", "thumbnail")):
            return "creative_design"
        if any(k in t for k in ("github", "code", "program", "برمج", "تطبيق", "repository", "repo")):
            return "software_engineering"
        if task.target in {"chrome", "browser", "المتصفح"} or any(k in t for k in ("browser", "المتصفح", "ويب", "افتح الرابط")):
            return "browser_automation"
        return "general_agent"
