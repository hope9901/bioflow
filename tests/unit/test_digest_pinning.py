"""Digest-pinning surface — schema, ContainerSpec.pinned_image, and the
runner using the pinned form when available."""
from __future__ import annotations

from bioflow.core.registry import ContainerSpec, Tool, load_registry


# ---------------------------------------------------------------------------
# ContainerSpec.pinned_image
# ---------------------------------------------------------------------------

class TestPinnedImage:

    def test_unpinned_returns_plain_image(self):
        c = ContainerSpec(image="quay.io/biocontainers/fastp:0.23.4--h5f740d0_0")
        assert c.pinned_image == "quay.io/biocontainers/fastp:0.23.4--h5f740d0_0"

    def test_pinned_swaps_tag_for_digest(self):
        digest = "sha256:" + "a" * 64
        c = ContainerSpec(
            image="quay.io/biocontainers/fastp:0.23.4--h5f740d0_0",
            image_digest=digest,
        )
        assert c.pinned_image == f"quay.io/biocontainers/fastp@{digest}"

    def test_image_without_tag_still_works(self):
        digest = "sha256:" + "b" * 64
        c = ContainerSpec(image="staphb/quast", image_digest=digest)
        assert c.pinned_image == f"staphb/quast@{digest}"

    def test_image_already_digest_form_not_double_appended(self):
        digest = "sha256:" + "c" * 64
        # If someone wrote the image as `repo@sha256:…` directly, the
        # tag-stripping logic must not append a second @digest.
        c = ContainerSpec(
            image=f"staphb/prokka@{digest}",
            image_digest=digest,
        )
        # base = "staphb/prokka" → "staphb/prokka@<digest>"
        assert c.pinned_image == f"staphb/prokka@{digest}"


# ---------------------------------------------------------------------------
# Tool model accepts and round-trips an image_digest
# ---------------------------------------------------------------------------

class TestToolWithDigest:

    def test_tool_validates_with_digest(self):
        digest = "sha256:" + "e" * 64
        t = Tool.model_validate({
            "id": "fastp",
            "name": "fastp",
            "version": "0.23.4",
            "category": "qc",
            "stage": ["genome_assembly.step1"],
            "applicable": {"species": ["any"], "read_type": ["short"], "mode": ["any"]},
            "container": {
                "image": "quay.io/biocontainers/fastp:0.23.4--h5f740d0_0",
                "pull_policy": "if_not_present",
                "image_digest": digest,
            },
            "resources": {
                "min": {"cpu": 2, "ram_gb": 2},
                "recommended": {"cpu": 4, "ram_gb": 4},
                "arch": ["x86_64"],
            },
            "command_template": "fastp -i {r1} -I {r2}",
        })
        assert t.container.image_digest == digest
        assert "@sha256:" in t.container.pinned_image


# ---------------------------------------------------------------------------
# Schema rejects malformed digests
# ---------------------------------------------------------------------------

class TestSchemaValidation:

    def _schema(self):
        import pathlib

        import yaml

        return yaml.safe_load(
            pathlib.Path("registry/schema.yaml").read_text(encoding="utf-8")
        )

    def _doc(self, digest):
        return {
            "id": "x",
            "name": "x",
            "version": "1",
            "category": "qc",
            "stage": ["s1"],
            "applicable": {"species": ["any"], "read_type": ["short"], "mode": ["any"]},
            "container": {
                "image": "img:1",
                "image_digest": digest,
            },
            "resources": {
                "min": {"cpu": 1, "ram_gb": 1},
                "recommended": {"cpu": 1, "ram_gb": 1},
            },
            "command_template": "echo hi",
        }

    def test_valid_digest_passes(self):
        from jsonschema import Draft202012Validator

        v = Draft202012Validator(self._schema())
        errors = list(v.iter_errors(self._doc("sha256:" + "f" * 64)))
        # Filter to only image_digest-related errors
        digest_errors = [e for e in errors if "image_digest" in str(e.path)]
        assert digest_errors == []

    def test_wrong_length_fails(self):
        from jsonschema import Draft202012Validator

        v = Draft202012Validator(self._schema())
        errors = list(v.iter_errors(self._doc("sha256:abc")))
        assert any("image_digest" in str(e.path) or "pattern" in e.message
                   for e in errors)

    def test_wrong_prefix_fails(self):
        from jsonschema import Draft202012Validator

        v = Draft202012Validator(self._schema())
        errors = list(v.iter_errors(self._doc("md5:" + "0" * 32)))
        assert any("image_digest" in str(e.path) or "pattern" in e.message
                   for e in errors)


# ---------------------------------------------------------------------------
# Runner uses pinned image when present
# ---------------------------------------------------------------------------

class TestRunnerUsesPinnedImage:

    def test_run_plan_sends_pinned_image_to_backend(self, tmp_path, monkeypatch):
        """run_plan must pass ``image@digest`` to the backend, not the bare tag."""
        # Build a minimal hand-rolled ExecutionPlan + registry pair so we
        # don't have to materialise a full YAML registry on disk.
        from bioflow.core.planner import ExecutionPlan, StagePlan
        from bioflow.core.runner import MockBackend, run_plan

        digest = "sha256:" + "9" * 64
        tool = Tool.model_validate({
            "id": "fastp",
            "name": "fastp",
            "version": "0.23.4",
            "category": "qc",
            "stage": ["s1"],
            "applicable": {"species": ["any"], "read_type": ["short"], "mode": ["any"]},
            "container": {
                "image": "quay.io/biocontainers/fastp:0.23.4--h5f740d0_0",
                "image_digest": digest,
            },
            "resources": {
                "min": {"cpu": 2, "ram_gb": 2},
                "recommended": {"cpu": 4, "ram_gb": 4},
            },
            "command_template": "echo {out_dir}",
        })

        # Patch load_registry to return our tool, so we don't need the
        # registry directory on disk.
        monkeypatch.setattr(
            "bioflow.core.runner.load_registry", lambda _d: [tool]
        )

        plan = ExecutionPlan(
            pipeline="genome_assembly",
            species="any",
            read_type="short",
            mode="any",
            workdir=str(tmp_path),
            stages=[StagePlan(stage_id="s1", tool_id="fastp", params={})],
            inputs={},
            registry_dir=tmp_path,  # ignored thanks to the monkeypatch
        )
        backend = MockBackend()
        run_plan(plan, backend=backend, show_progress=False)

        assert backend.calls, "MockBackend recorded no calls"
        assert backend.calls[0]["image"] == f"quay.io/biocontainers/fastp@{digest}"


# ---------------------------------------------------------------------------
# Live registry — at least some tools are pinned
# ---------------------------------------------------------------------------

def test_at_least_one_real_tool_is_pinned():
    """Regression guard: once a tool gains a digest in-tree it must keep one."""
    from bioflow.core.registry import default_registry_dir

    tools = load_registry(default_registry_dir())
    pinned = [t for t in tools if t.container.image_digest]
    # The current registry has fastp / spades / quast / prokka / bwa pinned.
    # Don't pin the exact count — this just guards against regression to 0.
    assert len(pinned) >= 5, (
        f"expected ≥ 5 pinned tools, got {len(pinned)}; "
        "did a registry rewrite drop image_digest entries?"
    )
