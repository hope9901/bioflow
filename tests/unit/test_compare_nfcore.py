"""Unit tests for the nf-core concordance scoring harness.

The harness lives in scripts/, so we import it by path.
"""
from __future__ import annotations

import gzip
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compare_nfcore.py"
_spec = importlib.util.spec_from_file_location("compare_nfcore", _SCRIPT)
cmp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cmp)


# ---------------------------------------------------------------------------
# VCF helpers
# ---------------------------------------------------------------------------

_VCF_HEADER = (
    "##fileformat=VCFv4.2\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE\n"
)


def _write_vcf(path: Path, records: list[str], gz: bool = False):
    body = _VCF_HEADER + "".join(r if r.endswith("\n") else r + "\n" for r in records)
    if gz:
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(body)
    else:
        path.write_text(body, encoding="utf-8")


def _rec(chrom, pos, ref, alt, filt="PASS", gt="0/1"):
    return f"{chrom}\t{pos}\t.\t{ref}\t{alt}\t50\t{filt}\tDP=30\tGT\t{gt}"


# ---------------------------------------------------------------------------
# compare_vcf
# ---------------------------------------------------------------------------

class TestVcf:

    def test_identical_vcfs_jaccard_one(self, tmp_path):
        recs = [_rec("chr20", 100, "A", "T"), _rec("chr20", 200, "G", "C")]
        a = tmp_path / "a.vcf"; _write_vcf(a, recs)
        b = tmp_path / "b.vcf"; _write_vcf(b, recs)
        r = cmp.compare_vcf(a, b)
        assert r["jaccard"] == 1.0
        assert r["genotype_concordance_on_shared"] == 1.0
        assert r["shared"] == 2

    def test_partial_overlap(self, tmp_path):
        a = tmp_path / "a.vcf"
        b = tmp_path / "b.vcf"
        _write_vcf(a, [_rec("chr20", 100, "A", "T"), _rec("chr20", 200, "G", "C")])
        _write_vcf(b, [_rec("chr20", 100, "A", "T"), _rec("chr20", 300, "G", "A")])
        r = cmp.compare_vcf(a, b)
        # 1 shared / 3 union; jaccard is rounded to 4 dp by the harness.
        assert r["shared"] == 1
        assert r["jaccard"] == 0.3333
        assert r["bioflow_only"] == 1
        assert r["reference_only"] == 1

    def test_gzip_input(self, tmp_path):
        a = tmp_path / "a.vcf.gz"
        b = tmp_path / "b.vcf.gz"
        _write_vcf(a, [_rec("chr20", 100, "A", "T")], gz=True)
        _write_vcf(b, [_rec("chr20", 100, "A", "T")], gz=True)
        r = cmp.compare_vcf(a, b)
        assert r["jaccard"] == 1.0

    def test_pass_only_filters_nonpass(self, tmp_path):
        a = tmp_path / "a.vcf"
        b = tmp_path / "b.vcf"
        _write_vcf(a, [_rec("chr20", 100, "A", "T", filt="LowQual")])
        _write_vcf(b, [_rec("chr20", 100, "A", "T")])
        # pass_only drops the bioflow record → no shared, union=1
        r = cmp.compare_vcf(a, b, pass_only=True)
        assert r["bioflow_variants"] == 0
        assert r["jaccard"] == 0.0
        # all-filters keeps it → identical
        r2 = cmp.compare_vcf(a, b, pass_only=False)
        assert r2["jaccard"] == 1.0

    def test_multiallelic_split(self, tmp_path):
        a = tmp_path / "a.vcf"
        b = tmp_path / "b.vcf"
        _write_vcf(a, [_rec("chr20", 100, "A", "T,C")])
        _write_vcf(b, [_rec("chr20", 100, "A", "T"), _rec("chr20", 100, "A", "C")])
        r = cmp.compare_vcf(a, b)
        assert r["bioflow_variants"] == 2     # split into two alleles
        assert r["jaccard"] == 1.0

    def test_genotype_discordance(self, tmp_path):
        a = tmp_path / "a.vcf"
        b = tmp_path / "b.vcf"
        _write_vcf(a, [_rec("chr20", 100, "A", "T", gt="0/1")])
        _write_vcf(b, [_rec("chr20", 100, "A", "T", gt="1/1")])
        r = cmp.compare_vcf(a, b)
        assert r["shared"] == 1
        assert r["genotype_concordance_on_shared"] == 0.0


# ---------------------------------------------------------------------------
# compare_counts + Spearman
# ---------------------------------------------------------------------------

class TestCounts:

    def test_spearman_perfect_monotonic(self):
        xs = [1.0, 2.0, 3.0, 4.0]
        ys = [10.0, 20.0, 30.0, 40.0]
        assert abs(cmp._spearman(xs, ys) - 1.0) < 1e-9

    def test_spearman_perfect_inverse(self):
        xs = [1.0, 2.0, 3.0, 4.0]
        ys = [40.0, 30.0, 20.0, 10.0]
        assert abs(cmp._spearman(xs, ys) + 1.0) < 1e-9

    def test_compare_counts_shared_genes(self, tmp_path):
        a = tmp_path / "a.tsv"
        b = tmp_path / "b.tsv"
        a.write_text("gene\tcount\nG1\t10\nG2\t20\nG3\t30\nG4\t5\n", encoding="utf-8")
        b.write_text("gene\tcount\nG1\t12\nG2\t22\nG3\t33\nG5\t99\n", encoding="utf-8")
        r = cmp.compare_counts(a, b)
        assert r["shared_genes"] == 3            # G1,G2,G3
        assert r["spearman_rho"] == 1.0          # monotonic on shared

    def test_compare_counts_skips_nonnumeric(self, tmp_path):
        a = tmp_path / "a.tsv"
        b = tmp_path / "b.tsv"
        a.write_text("gene\tcount\nG1\t10\nbad\tNA\nG2\t20\n", encoding="utf-8")
        b.write_text("gene\tcount\nG1\t11\nG2\t21\n", encoding="utf-8")
        r = cmp.compare_counts(a, b)
        assert r["shared_genes"] == 2


# ---------------------------------------------------------------------------
# CLI gate behaviour
# ---------------------------------------------------------------------------

class TestCliGate:

    def test_vcf_min_jaccard_gate_pass(self, tmp_path):
        a = tmp_path / "a.vcf"; _write_vcf(a, [_rec("chr20", 1, "A", "T")])
        b = tmp_path / "b.vcf"; _write_vcf(b, [_rec("chr20", 1, "A", "T")])
        rc = cmp.main(["vcf", "--bioflow", str(a), "--reference", str(b),
                       "--min-jaccard", "0.9"])
        assert rc == 0

    def test_vcf_min_jaccard_gate_fail(self, tmp_path):
        a = tmp_path / "a.vcf"; _write_vcf(a, [_rec("chr20", 1, "A", "T")])
        b = tmp_path / "b.vcf"; _write_vcf(b, [_rec("chr20", 2, "G", "C")])
        rc = cmp.main(["vcf", "--bioflow", str(a), "--reference", str(b),
                       "--min-jaccard", "0.9"])
        assert rc == 1

    def test_counts_writes_json(self, tmp_path):
        import json
        a = tmp_path / "a.tsv"; a.write_text("g\tc\nG1\t1\nG2\t2\n", encoding="utf-8")
        b = tmp_path / "b.tsv"; b.write_text("g\tc\nG1\t1\nG2\t2\n", encoding="utf-8")
        out = tmp_path / "r.json"
        rc = cmp.main(["counts", "--bioflow", str(a), "--reference", str(b),
                       "--out", str(out)])
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["type"] == "counts"
