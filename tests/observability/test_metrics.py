from src.observability.metrics import MetricsCollector


def test_metrics_collector_singleton():
    m1 = MetricsCollector.get_instance()
    m2 = MetricsCollector.get_instance()
    assert m1 is m2


def test_inc_streams_started():
    m = MetricsCollector.get_instance()
    before = m.streams_started_total.labels(platform="tiktok")._value.get()
    m.inc_stream_started("tiktok")
    after = m.streams_started_total.labels(platform="tiktok")._value.get()
    assert after == before + 1


def test_inc_streams_stopped():
    m = MetricsCollector.get_instance()
    before = m.streams_stopped_total.labels(platform="tiktok", reason="manual")._value.get()
    m.inc_stream_stopped("tiktok", "manual")
    after = m.streams_stopped_total.labels(platform="tiktok", reason="manual")._value.get()
    assert after == before + 1


def test_inc_highlight_created():
    m = MetricsCollector.get_instance()
    before = m.highlights_created_total.labels(type="FINAL")._value.get()
    m.inc_highlight("FINAL")
    after = m.highlights_created_total.labels(type="FINAL")._value.get()
    assert after == before + 1


def test_inc_pipeline_error():
    m = MetricsCollector.get_instance()
    before = m.pipeline_errors_total.labels(stage="stream_worker")._value.get()
    m.inc_pipeline_error("stream_worker")
    after = m.pipeline_errors_total.labels(stage="stream_worker")._value.get()
    assert after == before + 1


def test_observe_chunk_histogram():
    m = MetricsCollector.get_instance()
    m.observe_chunk(1.5, "s1")
    # no exception = pass


def test_observe_stt_histogram():
    m = MetricsCollector.get_instance()
    m.observe_stt(0.25)
    # no exception = pass


def test_observe_clip_gen_histogram():
    m = MetricsCollector.get_instance()
    m.observe_clip_gen(2.0)
    # no exception = pass


def test_set_llm_budget_remaining():
    m = MetricsCollector.get_instance()
    m.set_llm_budget_remaining(42)
    assert m.llm_budget_remaining._value.get() == 42.0
