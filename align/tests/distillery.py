#!/usr/bin/env python
import sys
from math import erf, sqrt, log

from .. import distillery, utils, align, seq

maxlen = 5

Tr = distillery.Translator(maxlen=5)

params = {
    'm':        3, # match score
    'tr':      -2, # transition score (A<->G and C<->T)
    'tv':      -2, # transversion score
    'go':      -3, # gap open score
    'ge':      -2, # gap extend score
    'hp_go':    0, # homopolymeric gap open score
    'hp_ge': -0.5, # homopolymeric gap extend score
    'band':    -1, # band width if positive
    'show_dp':  0, # whether to print the DP table
    'type': align.ALIGN_GLOBAL, # type of alignments
}

with open('data/dna.mtrtv.matrix') as f:
    subst_scores = eval(f.read().strip(), params)

A = seq.Alphabet('ACGT')
scores = Tr.translate_subst_scores(subst_scores, gopen=params['go'],
    gextend=params['ge'], homopoly_gopen=params['hp_go'],
    homopoly_gextend=params['hp_ge'])
alphabet = [x for _,_,x in Tr.translate_alphabet('ACGT')]
A_d = seq.Alphabet(alphabet)

s = 'AACCCCGGGGGGGGGGGGT'
t = 'AATGGGGGGGGGTTT'
s_d = Tr.distill(s)
t_d = Tr.distill(t)
S = seq.Sequence(s, A)
T = seq.Sequence(t, A)
print S
print T
opseq_d = 'BMSSS'
opseq = Tr.expand_opseq(s, t, opseq_d)
print opseq_d
print opseq
utils.print_alignment(S, T, '(0,0),0:' + opseq, sys.stdout)
S_d = seq.Sequence(s_d, A_d)
T_d = seq.Sequence(t_d, A_d)
C = align.AlignParams(alphabet=A_d,subst_scores=scores,
    gap_open_score=params['go'], gap_extend_score=params['ge'],
    max_diversion=params['band'])
P = align.AlignProblem(S=S_d, T=T_d, params=C,
    align_type=params['type'])
transcript = P.solve(print_dp_table=params['show_dp'])
print "opseq score: %.2f" % P.score(opseq_d)

print '\n' + transcript + '\n'
if transcript[:3] != 'Err':
    info,opseq_d = transcript.split(':')
    opseq = Tr.expand_opseq(S, T, opseq_d)
    utils.print_alignment(S, T, info + ':' + opseq, sys.stdout, margin=10)
