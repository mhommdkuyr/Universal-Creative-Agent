from .models import VerificationResult

class VerificationEngine:
    REQUIRED=('visual','timing','audio','text')
    def compare(self, reference: dict, output: dict, threshold: float=0.90) -> VerificationResult:
        issues=[f'missing:{k}' for k in self.REQUIRED if k not in output]
        metrics={k:float(output.get(k,0)) for k in self.REQUIRED}
        score=float(output.get('score', sum(metrics.values())/len(metrics) if not issues else 0.0))
        if score < threshold: issues.append(f'score_below_threshold:{score:.3f}')
        return VerificationResult(not issues,score,issues,metrics)
