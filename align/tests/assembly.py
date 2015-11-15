#!/usr/bin/env python
import sys
import os
import igraph

from .. import pw, tuples, seq, assembly

A = seq.Alphabet('ACGT')

params = {
    'wordlen': 5,           # tuple word lengths
    'genome_length': 5000,  # length of randomly generated genome
    'coverage': 5,          # coverage of random sequencing reads
    'read_len_mean': 500,   # average length of sequencing read
    'read_len_var': 10,     # variance of sequencing read length
    'go_prob': 0.05,        # gap open score
    'ge_prob': 0.3,         # gap extend score
    'subst_probs': [[0.97 if k==i else 0.01 for k in range(4)] for i in range(4)],
    'min_align_score': 120, # minimum overlap alignment score to constitue an edge
    'window': 20,           # rolling window length for tuple extension
    'drop_threshold': 10,   # what constitutes a drop in score of a window
    'max_succ_drops': 3     # how many consecutive drops are allowed
}
subst_scores = pw.AlignParams.subst_scores_from_probs(params['subst_probs'], A)
go_score, ge_score = pw.AlignParams.gap_scores_from_probs(params['go_prob'], params['ge_prob'])
C = pw.AlignParams(
    alphabet=A, subst_scores=subst_scores,
    go_score=go_score, ge_score=ge_score
)

def show_params():
    print 'Substitution probabilities:'
    for i in params['subst_probs']:
        print i
    print 'Substitution scores:'
    for i in subst_scores:
        print [round(f,2) for f in i]
    print 'Pr(go) = %.2f, Pr(ge) = %.2f +----> Score(go)=%.2f, Score(ge)=%.2f' % \
        (params['go_prob'], params['ge_prob'], go_score, ge_score)

    print 'drop_threshold = %.2f, max_succ_drops = %d, window = %d' % \
        (params['drop_threshold'], params['max_succ_drops'], params['window'])

def create_example(db):
    show_params()
    seq.make_sequencing_fixture('genome.fa', 'reads.fa',
        genome_length=params['genome_length'],
        coverage=params['coverage'],
        len_mean=params['read_len_mean'],
        len_var=params['read_len_var'],
        subst_probs=params['subst_probs'],
        ge_prob=params['ge_prob'],
        go_prob=params['go_prob']
    )
    B = tuples.TuplesDB(db, alphabet=A)
    B.initdb()
    B.populate('reads.fa');
    I = tuples.Index(B, wordlen=params['wordlen'])
    I.initdb()
    I.index()

def overlap_by_seed_extension(db, path):
    show_params()
    B = tuples.TuplesDB(db, alphabet=A)
    I = tuples.Index(B, wordlen=params['wordlen'])
    G = assembly.OverlapBuilder(I, C, **params).build()
    G.save(path)

def overlap_graph_by_known_order(db):
    """Builds the *correct* weighted, directed graph by using hints left in
    reads databse by ``seq.make_sequencing_fixture()``.

    Args:
        tuplesdb (tuples.TuplesDB): The tuples database.

    Returns:
        networkx.DiGraph
    """
    B = tuples.TuplesDB(db, alphabet=A)
    seqinfo = B.seqinfo()
    seqids = seqinfo.keys()
    vs = set()
    es, ws = [], []
    for sid_idx in range(len(seqids)):
        for tid_idx in range(sid_idx + 1, len(seqids)):
            S_id, T_id = seqids[sid_idx], seqids[tid_idx]
            S_info, T_info = seqinfo[S_id], seqinfo[T_id]
            S_min_idx, S_max_idx = S_info['start'], S_info['start'] + S_info['length']
            T_min_idx, T_max_idx = T_info['start'], T_info['start'] + T_info['length']
            S_name = '%s %d-%d #%d' % (S_info['name'], S_min_idx, S_max_idx, S_id)
            T_name = '%s %d-%d #%d' % (T_info['name'], T_min_idx, T_max_idx, T_id)
            vs = vs.union(set([S_name, T_name]))
            overlap = min(S_max_idx, T_max_idx) - max(S_min_idx, T_min_idx)
            if overlap > 0:
                if S_min_idx < T_min_idx:
                    es += [(S_name, T_name)]
                    ws += [overlap]
                elif S_min_idx > T_min_idx:
                    es += [(T_name, S_name)]
                    ws += [overlap]
                # if start is equal, edge goes from shorter read to longer read
                elif S_max_idx < T_max_idx:
                    es += [(S_name, T_name)]
                    ws += [overlap]
                elif S_max_idx > T_max_idx:
                    es += [(T_name, S_name)]
                    ws += [overlap]
                # if start and end is equal, reads are identical, ignore.

    G = assembly.OverlapGraph()
    G.iG.add_vertices(list(vs))
    es = [(G.iG.vs.find(name=u), G.iG.vs.find(name=v)) for u,v in es]
    G.iG.add_edges(es)
    G.iG.es['weight'] = ws
    return G
