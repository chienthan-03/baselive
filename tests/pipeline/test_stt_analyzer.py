from src.pipeline.stt_analyzer import STTAnalyzer
from src.core.models import TranscriptResult, TranscriptSegment


def test_stt_analyzer_speaking_rate_and_keywords():
    analyzer = STTAnalyzer()
    result = TranscriptResult(
        text="ôi trời ơi thật không",
        segments=[TranscriptSegment(0, 2, "ôi trời ơi thật không", 0.9)],
        language="vi",
        chunk_start_pts=0.0,
    )
    out = analyzer.analyze(result, duration_sec=2.0)
    assert out["speaking_rate"] > 0
    assert len(out["keyword_triggered"]) > 0
