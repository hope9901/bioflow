# cohort_small — reference for the joint_genotyping guard

`reference.fa` is the phiX genome (`phix_small/reference.fa`) with **5 SNPs
planted** at positions 800, 1600, 2400, 3200, 4000. The reads in
`phix_small/` were simulated from the *original* phiX, so aligning them against
this mutated reference yields five real variants — enough for the cohort to
carry records, not an empty VCF.

The `joint_genotyping` guard reuses `phix_small/`'s reads as two samples
(sampleA, sampleB) against this reference. GATK HaplotypeCaller → CombineGVCFs →
GenotypeGVCFs then produces a 2-sample `cohort.vcf.gz` with all five SNPs.

Only the reference lives here (5.5 kb); the reads are shared with `phix_small/`
to avoid duplicating them. The final SnpEff annotation stage is *not* guarded —
it downloads its organism database from S3 at run time, which would make CI
network-dependent and flaky.
