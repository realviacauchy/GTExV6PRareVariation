"""Makes file with following columns
Col1: Gene
Col2: Indiv
Col3: Comma separated list of variants

Col1 is restricted to genes that have at least one multi-tissue outlier
    individual
Col2 is all individuals that have at least one rare variant within 10kb TSS
    of the gene in that row
Col3 has each variant of the form $chrom:$position:$major_allele:$variant_allele

Example usage:
python make_gene_indiv_variants.py data/v8/outliers_medz_picked.txt \
download/gtex8/GTEx_AFA_10kb_TSS.vcf.gz \
reference/v8.genes.TSS_minus10k.bed \
reference/GTEx_AFA_10kb_TSS_AF_rare.frq \
reference/gene_indiv_variants.txt
"""

import os
import argparse
import pandas as pd
import allel

# parse arguments from command line
parser = argparse.ArgumentParser(
    description="Make file with outlier gene and individual pairs with list of rare variants"
)
parser.add_argument(
    "outliers", type=str, help="Input dir for multi-tissue outliers file"
)
parser.add_argument("vcf", type=str, help="Input dir for vcf file")
parser.add_argument(
    "TSS", type=str, help="Input dir for BED file with 10kb TSS of genes"
)
parser.add_argument(
    "rare_var",
    type=str,
    help="Input dir for allele frequency file with only rare variants",
)
parser.add_argument("outfile", type=str, help="output file")
args = parser.parse_args()

dir = os.environ["RAREVARDIR"] + "/"  # upper-level directory

outliers_file = dir + args.outliers  # data/v8/outliers_medz_picked.txt
vcf_file = dir + args.vcf  # download/gtex8/GTEx_AFA_10kb_TSS.vcf
TSS_file = dir + args.TSS  # reference/v8.genes.TSS_minus10k.bed
rare_var_file = dir + args.rare_var  # reference/GTEx_AFA_10kb_TSS_AF_rare.frq
outfile = dir + args.outfile

# read in files
print("reading input files")
outliers = pd.read_csv(outliers_file, sep="\t")
outliers.columns = map(str.lower, outliers.columns)

vcf = allel.read_vcf(vcf_file, numbers={"ALT": 1})  # assumes biallelic

TSS = pd.read_csv(TSS_file, sep="\t", names=["chrom", "start", "stop", "gene"])

rare_var = pd.read_csv(
    rare_var_file,
    sep="\t",
    skiprows=1,
    names=["chrom", "pos", "n_alleles", "n_chr", "ref", "alt"],
)
rare_var_chrom_pos = "$" + rare_var["chrom"] + ":$" + rare_var["pos"].astype(str)
rare_var.insert(rare_var.shape[1], "chrom:pos", rare_var_chrom_pos)
rare_var.drop_duplicates("chrom:pos", inplace=True)  # remove duplicates

# filter TSS for genes with outliers
TSS = TSS[TSS["gene"].isin(outliers["gene"])]

# filter rare_var for variants that are within a 10kb TSS window of outlier gene
# note that TSS has 0-based indexing whereas rare_var has 1-based indexing
print("filtering for rare variants within 10kb of TSS of outlier genes")
gene_dict = dict()  # dictionary with key=index, value=gene
rare_var["pos0"] = rare_var["pos"] - 1  # get 0-based indexing of rare_var
chr_list = list(TSS.drop_duplicates("chrom")["chrom"])
for chr in chr_list:
    TSS_chr = TSS[TSS["chrom"] == chr]
    rare_var_chr = rare_var[rare_var["chrom"] == chr]

    for _, row in TSS_chr.iterrows():
        # find rows in rare_var that are within a 10kb TSS of the outlier gene
        start = row["start"]
        stop = row["stop"] + 1
        idx_bool = rare_var_chr["pos0"].between(start, stop)
        rare_var_chr_index = list(rare_var_chr[idx_bool].index)

        # keep track of the gene associated with these variants
        for x in rare_var_chr_index:
            if x not in gene_dict.keys():
                gene_dict[x] = row["gene"]

rare_var_index = list(gene_dict.keys())
rare_var_index.sort()
rare_var = rare_var.loc[rare_var_index, :]

# add column for the gene associated with the position in rare_var
genes = [gene_dict[x] for x in rare_var_index]
rare_var.insert(0, "gene", genes)

# build dataframe from vcf file with columns
# chrom pos ref alt chrom:pos
vcf_df = pd.DataFrame(
    {
        "chrom": vcf["variants/CHROM"],
        "pos": vcf["variants/POS"],
        "ref": vcf["variants/REF"],
        "alt": vcf["variants/ALT"],
    }
)
vcf_df_chrom_pos = "$" + vcf_df["chrom"] + ":$" + vcf_df["pos"].astype(str)
vcf_df.insert(vcf_df.shape[1], "chrom:pos", vcf_df_chrom_pos)
dup_index = vcf_df.drop_duplicates("chrom:pos").index  # remove duplicates
vcf_df = vcf_df.loc[dup_index, :]

# get genotype data from vcf file
genotype = vcf["calldata/GT"]

# get list of samples from vcf file
samples = vcf["samples"]

# filter vcf_df and rare_var so that both contain the same chrom:pos
# find matching chrom and pos in rare_var and vcf_df
print("find matching chr and positions in rare variants list and the vcf file")
rare_var = rare_var[rare_var["chrom:pos"].isin(vcf_df["chrom:pos"])]
vcf_df = vcf_df[vcf_df["chrom:pos"].isin(rare_var["chrom:pos"])]

# add column for the gene associated with the variant in vcf_df
vcf_df.insert(0, "gene", rare_var["gene"].values)

# for each rare variant, find individuals that have the rare variant
# key=gene:indiv, value= list of $chrom:$position:$major_allele:$variant_allele
print("finding variants for gene-individual pairs")
gene_indiv_var = dict()

for i, index in enumerate(vcf_df.index):
    # determine major or minor allele from rare_var based on allele frequency
    ref = rare_var.iloc[i]["ref"].split(":")
    ref[1] = float(ref[1])
    alt = rare_var.iloc[i]["alt"].split(":")
    alt[1] = float(alt[1])

    if ref[1] > alt[1]:
        major = ref
        minor = alt
        rare_allele = 1
    else:
        major = alt
        minor = ref
        rare_allele = 0

    # check which samples have the rare allele
    for j, sample_gt in enumerate(genotype[index]):
        if rare_allele in sample_gt:
            gene = vcf_df.loc[index]["gene"]
            indiv = samples[j]

            k = gene + ":" + indiv
            if k not in gene_indiv_var:
                gene_indiv_var[k] = []

            var_list = gene_indiv_var[k]
            # $chrom:$position:$major_allele:$variant_allele
            chrom = vcf_df.loc[index]["chrom"]
            position = str(vcf_df.loc[index]["pos"])
            major_allele = major[0]
            variant_allele = minor[0]
            var_list.append(
                "$"
                + chrom
                + ":$"
                + position
                + ":$"
                + major_allele
                + ":$"
                + variant_allele
            )
            gene_indiv_var[k] = var_list

# write to file
gene_indiv_list = list(gene_indiv_var.keys())
gene_indiv_list.sort()

with open(outfile, "w") as f:
    # header
    f.write("gene\tindividual\tvariants\n")

    for gene_indiv in gene_indiv_list:
        gene, indiv = gene_indiv.split(":")
        var_list = gene_indiv_var[gene_indiv]
        variants = ",".join(var_list)
        f.write(gene + "\t" + indiv + "\t" + variants + "\n")

print("saved to", outfile)
