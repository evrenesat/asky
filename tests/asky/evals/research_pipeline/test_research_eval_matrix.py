from asky.evals.research_pipeline.matrix import load_matrix


def test_load_matrix_parses_profiles_and_defaults(tmp_path):
    matrix_path = tmp_path / "matrix.toml"
    matrix_path.write_text(
        """
dataset = "datasets/demo.yaml"

[[runs]]
id = "research-a"
model_alias = "gf"
research_mode = true

[runs.parameters]
temperature = 0.2

[[runs]]
id = "standard-b"
model_alias = "gf"
research_mode = false
source_provider = "live_web"
""".strip(),
        encoding="utf-8",
    )

    matrix = load_matrix(matrix_path)

    assert len(matrix.runs) == 2
    assert matrix.dataset_path is not None
    assert matrix.runs[0].resolved_source_provider() == "local_snapshot"
    assert matrix.runs[1].resolved_source_provider() == "live_web"
    assert matrix.runs[0].parameters["temperature"] == 0.2


def test_load_matrix_prefers_existing_cwd_relative_dataset_path(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    matrix_dir = workspace / "evals" / "research_pipeline" / "matrices"
    dataset_file = (
        workspace
        / "evals"
        / "research_pipeline"
        / "datasets"
        / "rfc_http_nist_v1.yaml"
    )
    matrix_dir.mkdir(parents=True)
    dataset_file.parent.mkdir(parents=True)
    dataset_file.write_text("id: demo\n", encoding="utf-8")

    matrix_path = matrix_dir / "default.toml"
    matrix_path.write_text(
        """
dataset = "evals/research_pipeline/datasets/rfc_http_nist_v1.yaml"

[[runs]]
id = "research-a"
model_alias = "gf"
research_mode = true
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(workspace)
    matrix = load_matrix(matrix_path)

    assert matrix.dataset_path == dataset_file.resolve()


def test_load_matrix_resolves_bare_output_root_from_cwd(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    matrix_dir = workspace / "configs"
    matrix_dir.mkdir(parents=True)

    matrix_path = matrix_dir / "matrix.toml"
    matrix_path.write_text(
        """
dataset = "./dataset.yaml"
output_root = "temp/research_eval/runs"

[[runs]]
id = "research-a"
model_alias = "gf"
research_mode = true
""".strip(),
        encoding="utf-8",
    )

    # Dataset path is matrix-relative because it uses ./ prefix.
    (matrix_dir / "dataset.yaml").write_text("id: demo\n", encoding="utf-8")

    monkeypatch.chdir(workspace)
    matrix = load_matrix(matrix_path)

    assert matrix.output_root == (workspace / "temp/research_eval/runs").resolve()
