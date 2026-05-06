from council.judge import parse_judgement_response, render_judge_prompt


def test_render_judge_prompt_replaces_placeholders():
    rendered = render_judge_prompt(
        "{{ task_description }}\n{{ transcript }}\n{{ output_a }}\n{{ output_b }}",
        task_description="Task",
        transcript="Transcript",
        output_a="A",
        output_b="B",
    )

    assert rendered == "Task\nTranscript\nA\nB"


def test_parse_judgement_response_accepts_json():
    parsed = parse_judgement_response('{"reasoning":"A is more grounded.","winner":"A"}')

    assert parsed.winner == "A"
    assert parsed.reasoning == "A is more grounded."


def test_parse_judgement_response_falls_back_to_tie_for_bad_winner():
    parsed = parse_judgement_response('{"reasoning":"Close.","winner":"C"}')

    assert parsed.winner == "TIE"

