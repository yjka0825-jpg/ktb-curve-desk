import os

os.environ["DASHBOARD_OFFLINE"] = "1"

from streamlit.testing.v1 import AppTest


def test_dashboard_renders_and_budget_updates():
    app = AppTest.from_file("app.py", default_timeout=30)
    app.run()
    assert not app.exception
    assert any("국고채 전 만기" in item.value for item in app.markdown)
    assert len(app.metric) >= 12

    app.number_input[0].set_value(100.0)
    app.number_input[1].set_value(25.0)
    app.number_input[2].set_value(0.5)
    app.button[0].click()
    app.run()
    assert not app.exception
    assert any("75.0 억원" in metric.value for metric in app.metric)
