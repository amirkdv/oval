import numpy as np
import os
import matplotlib.gridspec as gridspec
import matplotlib
from matplotlib import pyplot as plt
from itertools import combinations

import logging

from biseqt.util import ProgressIndicator
from biseqt.blot import HomologyFinder, band_radius
from biseqt.blot import band_radius
from biseqt.sequence import Alphabet
from biseqt.stochastics import rand_seq, MutationProcess, rand_read
from biseqt.kmers import KmerCache

from util import pickle_dump, pickle_load, plot_classifier

ALPHABET = Alphabet('ACGT')
LEISH_PATH = os.path.join(os.path.dirname(__file__), 'data/leishmania/reference.fa')
load_real = False
if load_real:
    with open(LEISH_PATH) as f:
        LEISH_SEQ = ''.join([x.strip().upper() for x in f.readlines() if x[0] != '>'])

    LEISH_SEQ = ALPHABET.parse(''.join([x for x in LEISH_SEQ if x in ALPHABET]))


# FIXME absorb as much as possible into stochastics and then move to
# experiments/util.py
def rand_seq_pair(N, related=False, real=False, mutation_process=None):
    if not related:
        assert isinstance(mutation_process, MutationProcess)
    if not real:
        S = rand_seq(ALPHABET, N)
        if related:
            T, _ = mutation_process.mutate(S)
        else:
            T = rand_seq(ALPHABET, N)
    else:
        if related:
            assert N < len(LEISH_SEQ)
            nS = np.random.randint(0, len(LEISH_SEQ) - N)
            S = LEISH_SEQ[nS:nS+N]
            T, _ = mutation_process.mutate(S)
        else:
            assert N * 2 < len(LEISH_SEQ)
            nS = np.random.randint(0, len(LEISH_SEQ) - 2 * N)
            nT = np.random.randint(nS, len(LEISH_SEQ) - N)
            S = LEISH_SEQ[nS:nS+N]
            T = LEISH_SEQ[nT:nT+N]
    return S, T


# Add unrelated sequences to the end of the given sequences
def pad_seq_pair(S, T, pad_length, ends='right'):
    assert pad_length >= 0
    junk = lambda : rand_seq(ALPHABET, pad_length)
    if ends in ['both', 'left']:
        S = junk() + S
        T = junk() + T
    if ends in ['both', 'right']:
        S = S + junk()
        T = T + junk()
    return S, T

def adjust_pw_plot(ax, N0, N1):
    ax.set_ylim(-N0 * .1, N0 * 1.1)
    ax.set_xlim(-N1 * .1, N1 * 1.1)
    ax.set_xlabel('Pos. in T', fontsize=12)
    ax.set_ylabel('Pos. in S', fontsize=12)
    ax.set_aspect('equal')
    line_kw = {'c': 'k', 'alpha': .1, 'lw':'5'}
    ax.axvline(x=-5,  **line_kw)
    ax.axvline(x=N1+5, **line_kw)
    ax.axhline(y=-5,  **line_kw)
    ax.axhline(y=N0+5, **line_kw)
    ax.invert_yaxis()
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position('top')
    ax.tick_params(labelsize=10)


# FIXME absorb as much as possible into SeedIndex
def plot_seeds(ax, seeds, N0, N1, c='k'):
    idx_S, idx_T = [], []
    for seed in seeds:
        idx_S.append(seed[0])
        idx_T.append(seed[1])

    # x and y are flipped when going from matrix notation to plotting.
    ax.scatter(idx_T, idx_S, facecolor=c, lw=0, s=2, alpha=.3)
    ax.grid(True)

def plot_similar_segment(ax, segment, color):
    (d_min, d_max), (a_min, a_max) = segment
    seg_ds = [d_min, d_min, d_max, d_max]
    seg_as = [a_min, a_max, a_max, a_min]

    seg_xs = [0, 0, 0, 0]
    seg_ys = [0, 0, 0, 0]
    for i in range(4):
        d, a = seg_ds[i], seg_as[i]
        x, y = (a + max(d, 0), a - min(d, 0))
        # x and y is flipped between matrix notation and plotting
        seg_xs[i], seg_ys[i] = y, x

    im = ax.fill(seg_xs, seg_ys, facecolor=color, edgecolor='none', lw=1, alpha=.3)

def plot_global_alignment(ax, opseq, **kw):
    xs, ys = [0], [0]
    for op in opseq:
        if op in 'MS':
            xs.append(xs[-1] + 1)
            ys.append(ys[-1] + 1)
        elif op == 'I':
            xs.append(xs[-1])
            ys.append(ys[-1] + 1)
        elif op == 'D':
            xs.append(xs[-1] + 1)
            ys.append(ys[-1])

    ax.plot(xs, ys, **kw)


# =======================
# Performance of Statistics in separating +/- cases
# Two scores are considered: z score wrt H0 and wrt H1
# =======================
# K is segment length of interest
from util import plot_with_sd
def plot_stats_performance_fixed_K(K, ns, n_samples, real=False, wordlen=None,
                           gap=None, subst=None, num_sds=1, banded=False,
                           replot=False, dumpfile=None):
    if replot:
        results = pickle_load(dumpfile)
    else:
        M = MutationProcess(ALPHABET, subst_probs=subst, ge_prob=gap, go_prob=gap)
        shape = (len(ns), n_samples)
        HF_kw = {'gap_prob': gap, 'subst_prob': subst,
                 'sensitivity': .9, 'alphabet': ALPHABET, 'wordlen': wordlen,
                 'path': ':memory:', 'log_level': logging.WARNING}
        results = {
            'H0': {'pos': np.zeros(shape), 'neg': np.zeros(shape)},
            'H1': {'pos': np.zeros(shape), 'neg': np.zeros(shape)},
            'banded': banded,
            'HF_kw': HF_kw,
            # FIXME put in other info as well
        }
        for n_idx, n in enumerate(ns):
            print 'n = %d (%d/%d)' % (n, n_idx+1, len(ns))
            for i in range(n_samples):
                S, T = rand_seq_pair(K, real=real, related=False, mutation_process=M)
                S, T = pad_seq_pair(S, T, n-K)
                HF = HomologyFinder(S, T, **HF_kw)
                if banded:
                    radius = HF.band_radius(K)
                    A = 2 * n * radius
                    num_seeds = HF.seed_count(d_band=(-radius, radius))
                else:
                    A = n ** 2
                    num_seeds = HF.seed_count()
                s0, s1 = HF.score_num_seeds(num_seeds=num_seeds, area=A, seglen=K)
                results['H0']['neg'][n_idx][i] = s0
                results['H1']['neg'][n_idx][i] = s1

            for i in range(n_samples):
                S, T = rand_seq_pair(K, real=real, related=True, mutation_process=M)
                S, T = pad_seq_pair(S, T, n-K)
                HF = HomologyFinder(S, T, **HF_kw)
                if banded:
                    radius = HF.band_radius(K)
                    A = n * radius
                    num_seeds = HF.seed_count(d_band=(-radius, radius))
                else:
                    A = n ** 2
                    num_seeds = HF.seed_count()
                s0, s1 = HF.score_num_seeds(num_seeds=num_seeds, area=A, seglen=K)
                results['H0']['pos'][n_idx][i] = s0
                results['H1']['pos'][n_idx][i] = s1

        if dumpfile:
            pickle_dump(dumpfile, results, comment='stats performance')

    fig = plt.figure(figsize=(15, 6))
    ax_H0 = fig.add_subplot(1, 2, 1)
    ax_H1 = fig.add_subplot(1, 2, 2)


    kw = {'marker': 'o', 'markersize': 5, 'lw': 2, 'alpha': .8}
    _ns = [n/1000. for n in ns]

    for key, ax in zip(['H0', 'H1'], [ax_H0, ax_H1]):
        for case, color in zip(['pos', 'neg'], ['g', 'r']):
            plot_with_sd(ax, _ns, results[key][case], axis=1, color=color, **kw)
            ax.grid(True)

        ax.set_ylabel('%s score' % key, fontsize=14)
        ax.set_xlabel('sequence length (kb)', fontsize=14)

    fig.suptitle('word len. = %d, segment len. = %d, # samples = %d' % (wordlen, K, n_samples), fontweight='bold')
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    fig.savefig('stats performance - banded', dpi=300)


def plot_stats_performance_unknown_K(n, Ks_hf, Ks_true, n_samples,
                                     real=False, wordlen=None, gap=None, subst=None,
                                     num_sds=1, replot=False, dumpfile=None):
    assert n > max(Ks)
    assert np.all(np.diff(Ks) > 0)
    if replot:
        results = pickle_load(dumpfile)
    else:
        a
        M = MutationProcess(ALPHABET, subst_probs=subst, ge_prob=gap, go_prob=gap)
        shape = (len(Ks_true), len(Ks_hf), n_samples)
        HF_kw = {'gap_prob': gap, 'subst_prob': subst,
                 'sensitivity': .9, 'alphabet': ALPHABET, 'wordlen': wordlen,
                 'path': ':memory:', 'log_level': logging.WARNING}
        _zero = lambda: {'pos': np.zeros(shape), 'neg': np.zeros(shape)}
        results = {
            'H0': {'band': _zero(), 'segment': _zero()},
            'H1': {'band': _zero(), 'segment': _zero()},
            'HF_kw': HF_kw,
            'n_samples': n_samples,
            'Ks_hf': Ks_hf,
            'Ks_true': Ks_true,
            'real': real,
        }
        for K_true_idx, K_true in enumerate(Ks_true):
            for K_hf_idx, K_hf in enumerate(Ks_hf):
                print 'K_true = %d, K_hf = %d' % (K_true, K_hf)
                for i in range(n_samples):
                    for case in ['neg', 'pos']:
                        if case == 'pos':
                            S, T = rand_seq_pair(K_true, real=real, related=True, mutation_process=M)
                            S, T = pad_seq_pair(S, T, (n - K_true)/2, ends='both')
                        else:
                            S, T = rand_seq_pair(n, real=real, related=False, mutation_process=M)
                        HF = HomologyFinder(S, T, **HF_kw)
                        radius = HF.band_radius(K_hf)
                        A = 2 * K_hf * radius
                        num_seeds = HF.seed_count(d_band=(-radius, radius))
                        s0_band, s1_band = HF.score_num_seeds(num_seeds=num_seeds, area=A, seglen=K_hf)
                        results['H0']['band'][case][K_true_idx][K_hf_idx][i] = s0_band
                        results['H1']['band'][case][K_true_idx][K_hf_idx][i] = s1_band

                        s0_segs = [s for _, s, _ in HF.highest_scoring_segments(K_hf, mode='H0')]
                        s1_segs = [s for _, s, _ in HF.highest_scoring_segments(K_hf, mode='H1')]
                        results['H0']['segment'][case][K_true_idx][K_hf_idx][i] = max(s0_segs)
                        results['H1']['segment'][case][K_true_idx][K_hf_idx][i] = max(s1_segs)

        if dumpfile:
            pickle_dump(dumpfile, results, comment='stats performance')


    cmap = plt.cm.get_cmap('brg')
    colors = [cmap(i/(1.*len(Ks_hf)))[:3] for i in range(len(Ks_hf))]
    Ks_true, Ks_hf = results['Ks_true'], results['Ks_hf']
    wordlen, n_samples = results['HF_kw']['wordlen'], results['n_samples']
    gap, subst = results['HF_kw']['gap_prob'], results['HF_kw']['subst_prob']

    for stat in ['band', 'segment']:
        fig_roc = plt.figure(figsize=(12, 6)) # ROC curves for each of K_hf's
        ax_H0_roc = fig_roc.add_subplot(1, 2, 1)
        ax_H1_roc = fig_roc.add_subplot(1, 2, 2)

        fig_all = plt.figure(figsize=(12, 6)) # separate plots for each K_hf with var
        ax_H0_all = fig_all.add_subplot(1, 2, 1)
        ax_H1_all = fig_all.add_subplot(1, 2, 2)
        for K_hf_idx, K_hf in enumerate(Ks_hf):
            color = colors[K_hf_idx]
            for key, ax_all in zip(['H0', 'H1'], [ax_H0_all, ax_H1_all]):
                for ls, case in zip(['--', '-'], ['neg', 'pos']):
                    res = results[key][stat][case][:, K_hf_idx, :]
                    means = res.mean(axis=1)
                    sds = np.sqrt(res.var(axis=1))

                    ax_all.fill_between(Ks_true, means - num_sds * sds, means + num_sds * sds, facecolor=color, edgecolor=color, alpha=.2)

                    label = None if case == 'neg' else 'K = %d' % K_hf
                    ax_all.plot(Ks_true, means, lw=1, ls=ls, alpha=.7, c=color, label=label)

                ax_all.set_xlabel('True length of homologous region', fontsize=10)
                ax_all.set_ylabel('%s %s score' % (stat, key), fontsize=10)
                ax_all.grid(True)
                ax_all.axvline(x=K_hf, lw=4, alpha=.3, color=color)
            ax_H0_all.legend(loc='upper left', fontsize=10)

            # roc curves
            from bisect import bisect_left
            from plots import plot_roc
            K_true_idx = bisect_left(Ks_true, K_hf)
            #K_true_idx = 0
            label = 'K = %d' % K_hf
            pos_H0 = results['H0'][stat]['pos'][K_true_idx:, K_hf_idx, :].flatten()
            neg_H0 = np.concatenate([
                results['H0'][stat]['pos'][:K_true_idx, K_hf_idx, :].flatten(),
                results['H0'][stat]['neg'][:, K_hf_idx, :].flatten()
            ])

            pos_H1 = results['H1'][stat]['pos'][K_true_idx:, K_hf_idx, :].flatten()
            neg_H1 = np.concatenate([
                results['H1'][stat]['pos'][:K_true_idx, K_hf_idx, :].flatten(),
                results['H1'][stat]['neg'][:, K_hf_idx, :].flatten()
            ])
            plot_roc(ax_H0_roc, pos_H0, neg_H0, lw=1.5, alpha=.8, classifier='>', color=color, label=label)
            plot_roc(ax_H1_roc, pos_H1, neg_H1, lw=1.5, alpha=.8, classifier='>', color=color, label=label)

        for mode, ax in zip(['H0', 'H1'], [ax_H0_roc, ax_H1_roc]):
            ax.grid(True)
            ax.set_title('ROC curve for %s %s score' % (stat, mode))
            ax.legend(loc='lower right', fontsize=10)
        title = 'word len. = %d, # samples = %d, seq. len = %d, ' % \
                (wordlen, n_samples, max(Ks_true)) + \
                'gap = %.2f, subst = %.2f' % (gap, subst)
        for _fig in [fig_all, fig_roc]:
            _fig.suptitle(title, fontsize=12)
            _fig.tight_layout(rect=[0, 0.03, 1, 0.95])
        fig_all.savefig('stats performance - banded - unknown K - max over peak - all [%s].png' % stat, dpi=300)
        fig_roc.savefig('stats performance - banded - unknown K - max over peak - ROC [%s].png' % stat, dpi=300)


def plot_stats_performance_unknown_g(n, K, gs_hf, gs_true, n_samples,
                                      real=False, wordlen=None, subst=None,
                                      num_sds=1, replot=False, dumpfile=None):
    assert n > max(Ks)
    assert np.all(np.diff(Ks) > 0)
    if replot:
        results = pickle_load(dumpfile)
    else:
        shape = (len(gs_true), len(gs_hf), n_samples)
        HF_kw = {'subst_prob': subst,
                 'sensitivity': .9, 'alphabet': ALPHABET, 'wordlen': wordlen,
                 'path': ':memory:', 'log_level': logging.WARNING}
        _zero = lambda: {'pos': np.zeros(shape), 'neg': np.zeros(shape)}
        results = {
            'H0': {'band': _zero(), 'segment': _zero()},
            'H1': {'band': _zero(), 'segment': _zero()},
            'HF_kw': HF_kw,
            'n_samples': n_samples,
            'gs_hf': gs_hf,
            'gs_true': gs_true,
            'n': n,
            'K': K,
            'real': real,
        }
        for g_true_idx, g_true in enumerate(gs_true):
            M = MutationProcess(ALPHABET, subst_probs=subst, ge_prob=g_true, go_prob=g_true)
            for g_hf_idx, g_hf in enumerate(gs_hf):
                print 'g_true = %.2f, g_hf = %.2f' % (g_true, g_hf)
                for i in range(n_samples):
                    for case in ['neg', 'pos']:
                        if case == 'pos':
                            S, T = rand_seq_pair(K, real=real, related=True, mutation_process=M)
                            S, T = pad_seq_pair(S, T, n - K)
                        else:
                            S, T = rand_seq_pair(n, real=real, related=False, mutation_process=M)
                        HF_kw['gap_prob'] = g_hf
                        HF = HomologyFinder(S, T, **HF_kw)
                        radius = HF.band_radius(K)
                        A = 2 * K * radius
                        num_seeds = HF.seed_count(d_band=(-radius, radius))
                        s0_band, s1_band = HF.score_num_seeds(num_seeds=num_seeds, area=A, seglen=K)
                        results['H0']['band'][case][g_true_idx][g_hf_idx][i] = s0_band
                        results['H1']['band'][case][g_true_idx][g_hf_idx][i] = s1_band

                        s0_segs = [s for _, s, _ in HF.highest_scoring_segments(K, mode='H0')]
                        s1_segs = [s for _, s, _ in HF.highest_scoring_segments(K, mode='H1')]
                        results['H0']['segment'][case][g_true_idx][g_hf_idx][i] = max(s0_segs)
                        results['H1']['segment'][case][g_true_idx][g_hf_idx][i] = max(s1_segs)

        if dumpfile:
            pickle_dump(dumpfile, results, comment='stats performance')


    cmap = plt.cm.get_cmap('brg')
    colors = [cmap(i/(1.*len(gs_hf)))[:3] for i in range(len(gs_hf))]
    gs_true, gs_hf = results['gs_true'], results['gs_hf']
    wordlen, n_samples = results['HF_kw']['wordlen'], results['n_samples']
    n, K, subst = results['n'], results['K'], results['HF_kw']['subst_prob']

    for stat in ['band', 'segment']:
        fig_roc = plt.figure(figsize=(12, 6)) # ROC curves for each of g_hf's
        ax_H0_roc = fig_roc.add_subplot(1, 2, 1)
        ax_H1_roc = fig_roc.add_subplot(1, 2, 2)

        fig_all = plt.figure(figsize=(12, 6)) # separate plots for each g_hf with var
        ax_H0_all = fig_all.add_subplot(1, 2, 1)
        ax_H1_all = fig_all.add_subplot(1, 2, 2)
        for g_hf_idx, g_hf in enumerate(gs_hf):
            color = colors[g_hf_idx]
            for key, ax_all in zip(['H0', 'H1'], [ax_H0_all, ax_H1_all]):
                for ls, case in zip(['--', '-'], ['neg', 'pos']):
                    res = results[key][stat][case][:, g_hf_idx, :]
                    means = res.mean(axis=1)
                    sds = np.sqrt(res.var(axis=1))

                    ax_all.fill_between(gs_true, means - num_sds * sds, means + num_sds * sds, facecolor=color, edgecolor=color, alpha=.2)

                    label = None if case == 'neg' else 'g = %.2f' % g_hf
                    ax_all.plot(gs_true, means, lw=1, ls=ls, alpha=.7, c=color, label=label)

                ax_all.set_xlabel('True gap probability of homologous region', fontsize=10)
                ax_all.set_ylabel('%s %s score' % (stat, key), fontsize=10)
                ax_all.grid(True)
                ax_all.axvline(x=g_hf, lw=4, alpha=.3, color=color)
            ax_H0_all.legend(loc='upper right', fontsize=10)

            # roc curves
            from bisect import bisect_left
            from plots import plot_roc
            g_true_idx = bisect_left(gs_true, g_hf)
            label = 'g = %.2f' % g_hf
            # NOTE pos and neg are different from 'unknown K' experiment, here
            # if g_true < g_hf we count it as positive.
            pos_H0 = results['H0'][stat]['pos'][:g_true_idx, g_hf_idx, :].flatten()
            neg_H0 = np.concatenate([
                results['H0'][stat]['pos'][g_true_idx:, g_hf_idx, :].flatten(),
                results['H0'][stat]['neg'][:, g_hf_idx, :].flatten()
            ])

            pos_H1 = results['H1'][stat]['pos'][:g_true_idx, g_hf_idx, :].flatten()
            neg_H1 = np.concatenate([
                results['H1'][stat]['pos'][g_true_idx:, g_hf_idx, :].flatten(),
                results['H1'][stat]['neg'][:, g_hf_idx, :].flatten()
            ])
            plot_roc(ax_H0_roc, pos_H0, neg_H0, lw=1.5, alpha=.8, classifier='>', color=color, label=label)
            plot_roc(ax_H1_roc, pos_H1, neg_H1, lw=1.5, alpha=.8, classifier='>', color=color, label=label)

        for mode, ax in zip(['H0', 'H1'], [ax_H0_roc, ax_H1_roc]):
            ax.grid(True)
            ax.set_title('ROC curve for %s %s score' % (stat, mode))
            ax.legend(loc='lower right', fontsize=10)
        title = 'word len. = %d, # samples = %d, seq. len = %d, ' % \
                (wordlen, n_samples, n) + \
                'homology len = %d, subst = %.2f' % (K, subst)
        for _fig in [fig_all, fig_roc]:
            _fig.suptitle(title, fontsize=12)
            _fig.tight_layout(rect=[0, 0.03, 1, 0.95])
        fig_all.savefig('stats performance - banded - unknown g - rescore seg - all [%s].png' % stat, dpi=300)
        fig_roc.savefig('stats performance - banded - unknown g - rescore seg - ROC [%s].png' % stat, dpi=300)

def plot_stats_performance_estimate_seg_properties(n, Ks, g_hf, gs, n_samples,
                                      real=False, wordlen=None, subst=None,
                                      num_sds=1, replot=False, dumpfile=None):
    assert n > max(Ks)
    assert np.all(np.diff(Ks) > 0)
    if replot:
        results = pickle_load(dumpfile)
    else:
        shape = (len(gs), len(Ks), n_samples)
        HF_kw = {'subst_prob': subst,
                 'sensitivity': .9, 'alphabet': ALPHABET, 'wordlen': wordlen,
                 'path': ':memory:', 'log_level': logging.WARNING}
        _zero = lambda: np.zeros(shape)
        results = {
            'H0': {'match_p': _zero(), 'length': _zero()},
            'H1': {'match_p': _zero(), 'length': _zero()},
            'HF_kw': HF_kw,
            'n_samples': n_samples,
            'g_hf': g_hf,
            'gs': gs,
            'Ks': Ks,
            'n': n,
            'real': real,
        }
        for g_idx, g in enumerate(gs):
            M = MutationProcess(ALPHABET, subst_probs=subst, ge_prob=g, go_prob=g)
            for K_idx, K in enumerate(Ks):
                print 'g = %.2f, K= %d' % (g, K)
                for i in range(n_samples):
                    S, T = rand_seq_pair(K, real=real, related=True, mutation_process=M)
                    S, T = pad_seq_pair(S, T, (n - K)/2, ends='both')

                    # NOTE if g_hf is not given, use an exact model
                    HF = HomologyFinder(S, T, gap_prob=g_hf if g_hf is not None else g,**HF_kw)

                    for mode in ['H0', 'H1']:
                        for segment, _, match_p in HF.highest_scoring_segments(K, mode=mode):
                            if not segment:
                                continue
                            (d_min, d_max), (a_min, a_max) = segment
                            if d_min <= 0 <= d_max:
                                results[mode]['match_p'][g_idx][K_idx][i] = match_p
                                results[mode]['length'][g_idx][K_idx][i] = a_max - a_min
                                print S.content_id[:8], T.content_id[:8], mode, match_p, a_max - a_min
                                break
                        # if we get to here without setting estimated match p
                        # and homology length, they will just be 0

        if dumpfile:
            pickle_dump(dumpfile, results, comment='stats performance')


    cmap = plt.cm.get_cmap('brg')
    colors = [cmap(i/(1.*len(gs)))[:3] for i in range(len(gs))]
    gs, Ks, n, subst = results['gs'], results['Ks'], results['n'], results['HF_kw']['subst_prob']
    wordlen, n_samples = results['HF_kw']['wordlen'], results['n_samples']
    g_hf = results['g_hf']

    # Estimated match probability
    fig_H0 = plt.figure(figsize=(12, 6))
    ax_H0_p = fig_H0.add_subplot(1, 2, 1)
    ax_H0_K = fig_H0.add_subplot(1, 2, 2)
    # Estimated length
    fig_H1 = plt.figure(figsize=(12, 6))
    ax_H1_p = fig_H1.add_subplot(1, 2, 1)
    ax_H1_K = fig_H1.add_subplot(1, 2, 2)
    for g_idx, g in enumerate(gs):
        color = colors[g_idx]
        for key, ax in zip(['H0', 'H1'], [ax_H0_p, ax_H1_p]):
            ax.set_ylim(.7, 1.1)
            res = results[key]['match_p'][g_idx, :, :]
            # HACK
            if not np.count_nonzero(res):
                continue
            res[res == 0] = 'nan'
            means = np.nanmean(res, axis=1)
            sds = np.sqrt(np.nanvar(res, axis=1))

            true_match = (1 - g) * (1 - subst)
            label = 'p = %.2f' % true_match
            ax.plot(Ks, means, lw=2, alpha=.7, c=color, label=label)
            ax.fill_between(Ks, means - num_sds * sds, means + num_sds * sds, facecolor=color, edgecolor=color, alpha=.1)

            ax.set_xlabel('Length of homologous region', fontsize=10)
            ax.set_ylabel('Estimated match probability from %s segment' % key, fontsize=10)
            ax.grid(True)
            ax.axhline(y=true_match, lw=1.5, ls='--', alpha=.8, color=color)
        ax_H0_p.legend(loc='upper right', fontsize=10)
        for key, ax in zip(['H0', 'H1'], [ax_H0_K, ax_H1_K]):
            ax.set_xlim(0, 1.1 * max(Ks))
            res = results[key]['length'][g_idx, :, :]

            # HACK
            if not np.count_nonzero(res):
                continue
            res[res == 0] = 'nan'
            means = np.nanmean(res, axis=1)
            sds = np.sqrt(np.nanvar(res, axis=1))

            true_match = (1 - g) * (1 - subst)
            label = 'p = %.2f' % true_match
            ax.plot(Ks, means, lw=2, alpha=.7, c=color, label=label)
            ax.fill_between(Ks, means - num_sds * sds, means + num_sds * sds, facecolor=color, edgecolor=color, alpha=.1)

            ax.set_xlabel('Length of homologous region', fontsize=10)
            ax.set_ylabel('Estimated length from %s segment' % key, fontsize=10)
            ax.grid(True)
        ax_H0_K.legend(loc='upper left', fontsize=10)
        ax_H1_K.legend(loc='upper left', fontsize=10)
        _Ks = np.insert(Ks, [0], 0)
        ax_H0_K.plot(_Ks, _Ks, lw=1, ls='--', alpha=.3, c='k')
        ax_H1_K.plot(_Ks, _Ks, lw=1, ls='--', alpha=.3, c='k')

    title = 'word len. = %d, seq. len = %d, # samples = %d, subst = %.2f, model gap = %s' % \
            (wordlen, n, n_samples, subst, 'exact' if g_hf is None else str(round(g_hf, 2)))
    for fig, mode in zip([fig_H0, fig_H1], ['H0', 'H1']):
        fig.suptitle(title, fontsize=12)
        fig.tight_layout(rect=[0, 0.03, 1, 0.95])
        fig.savefig('stats performance - banded - homology properties %s%s.png' % (mode, ' (exact)' if g_hf is None else ''), dpi=300)

# FIXME there are 3 different experiments in here now
def exp_stats_performance():
    K = 500 # similar segment length
    ns = [i*K for i in range(1, 11)] # sequence lengths
    n_samples = 100 # number samples for each n

    wordlen = 8
    gap = .1
    subst = .1
    dumpfile = 'stats_performance_banded K=%d.txt' % K
    plot_stats_performance_fixed_K(K, ns, n_samples, real=False, banded=True, subst=subst, gap=gap, wordlen=wordlen, dumpfile=dumpfile, replot=True)
    raise

    # NOTE unknown K experiment
    Ks_hf = [500, 1000, 2000, 4000]
    Ks_true = [i*300 for i in range(1, 17)] # sequence lengths
    n_samples = 50 # number samples for each n
    n = 50000

    dumpfile = 'stats_performance_banded_unknown_K_max_over_peak.txt'
    plot_stats_performance_unknown_K(n, Ks_hf, Ks_true, n_samples,
        real=False, subst=subst, gap=gap, wordlen=wordlen, dumpfile=dumpfile, replot=False)

    # ==========================
    # NOTE this is the unkonwn gap experiment
    # TODO we're still at 70% identity and above, move subst to get to lower
    # values? subst = .3, gap = .3 gives .49 which should be enough.
    #subst = .02
    #gs_hf = [.04, .08, .12, .16]
    ##Ks_hf = [1000, 2000, 4000]
    #gs_true = np.arange(.01, .22, .02)
    #K = 500
    #n = 25000
    #n_samples = 10 # number samples for each n

    #dumpfile = 'stats_performance_banded_unknown_g_rescore_seg.txt'
    #plot_stats_performance_unknown_g(n, K, gs_hf, gs_true, n_samples,
        #real=False, subst=subst, wordlen=wordlen, dumpfile=dumpfile, replot=False)

    #raise
    # ===============================
    # NOTE this is length/prob estimation experiment
    #subst = .02
    ##Ks_hf = [1000, 2000, 4000]
    #gs = [.02, .08, .14, .2]
    #Ks = [i*200 for i in range(2, 31)] # sequence lengths
    #n = 12000
    #n_samples = 10 # number samples for each n

    #g_hf = .1
    #dumpfile = 'stats_performance_banded_estimate_seg_properties.txt'
    ##g_hf = None
    ##dumpfile = 'stats_performance_banded_estimate_seg_properties[exact].txt'
    #plot_stats_performance_estimate_seg_properties(n, Ks, g_hf, gs, n_samples,
        #real=False, subst=subst, wordlen=wordlen, dumpfile=dumpfile, replot=False)

def exp_local_alignment():
    gap = .2
    subst = .1
    K = 500

    # HACK for debugging overlaps; if gap probs for HF are not large enough, we
    # don't see it!
    #gap = .2
    #subst = .2
    #K = 1700

    wordlen = 8
    # NOTE I can drive sensitivity to 0 and get decent results
    HF_kw = {'g_max': .2, 'sensitivity': .9, 'alphabet': ALPHABET,
             'wordlen': wordlen,
             'path': 'example.db', 'log_level': logging.INFO}

    M = MutationProcess(ALPHABET, subst_probs=subst, ge_prob=gap, go_prob=gap)

    homs = [rand_seq(ALPHABET, i) for i in [200, 500, 1500, 2500]]
    junk = lambda: rand_seq(ALPHABET, np.random.randint(1000, 2000))

    S = junk() + homs[0] + junk() + homs[1] + junk() + homs[3] + \
        junk() + homs[2] + junk() + homs[2] + junk() + homs[0] + junk()
    homs = [M.mutate(homs[i])[0] for i in range(len(homs))]
    T = junk() + homs[3] + junk() + homs[2] + junk() + homs[0] + \
        junk() + homs[3] + junk() + homs[1] + junk() + homs[2] + junk()

    #K = 2500
    #n = 10000
    #S, T = rand_seq_pair(K, real=False, related=True, mutation_process=M)
    #S, T = pad_seq_pair(S, T, n - K)
    #K = 4000 # for HF

    # NOTE having a higher than reality gap probability in model allows shorter
    # but more similar regions to leak in. However you score the final segment,
    # i.e either based on required seglen or a_peak (a_max - a_min).
    from util import load_fasta
    with open('data/actb/mm10.chr5.fa') as f:
        S, _, _ = load_fasta(f, ALPHABET).next()
    with open('data/actb/hg38.chr7.fa') as f:
        T, _, _ = load_fasta(f, ALPHABET).next()
    with open('data/actb/hg38.chr7_mm10.chr5.fa') as f:
        f.readline()
        opseq = f.readline().strip()

    #print 'mm10.chr5', S
    #print '------------------'
    #print 'hg38.chr7', T
    #print '------------------'
    #print 'opseq', opseq
    #raise
    K = 500
    print K, HF_kw



    fig = plt.figure()
    gs = gridspec.GridSpec(1, 2, width_ratios=[30,1])
    ax = plt.subplot(gs[0])
    ax_colorbar = plt.subplot(gs[1])

    cmap = plt.cm.get_cmap('jet')

    max_score = 1

    print 'finding homologies'
    HF = HomologyFinder(S, T, **HF_kw)
    scores = []
    # FIXME two separate experiments that show that H1 is superior in not
    # seeing shorter than desired homologies. The two methods seem to be
    # identical. Tried H0 thresholds: 10, 50, 100
    #for segment, score, match_p in HF.similar_segments(K, mode='H1'):
    # FIXME why is it K_min=100, p_min=.7, mode='H1' finds stuff but p_min=.6
    # does not?!!
    for segment, score, match_p in HF.highest_scoring_segments(K_min=100, p_min=.7, mode='H1'):
        if segment is None:
            continue
        (d_min, d_max), (a_min, a_max) = segment
        print segment, score
        color = cmap(score/max_score)[:3]
        plot_similar_segment(ax, segment, color=color)
        scores.append(score)

    plot_global_alignment(ax, opseq, color='g', lw=4, alpha=.4)

    norm = matplotlib.colors.Normalize(vmin=0, vmax=max_score)
    plot_seeds(ax, HF.seeds(), len(S), len(T))
    adjust_pw_plot(ax, len(S), len(T))

    cb1 = matplotlib.colorbar.ColorbarBase(ax_colorbar, cmap=cmap, norm=norm, orientation='vertical')

    fig.tight_layout()
    fig.savefig('local alignment.png', dpi=500)

def exp_conserved_sequences():
    gap = .15
    subst = .15
    K = 500
    wordlen = 8
    HF_kw = {'gap_prob': gap, 'subst_prob': subst,
             'sensitivity': .9, 'alphabet': ALPHABET, 'wordlen': wordlen,
             'path': ':memory:', 'log_level': logging.INFO}

    M_std = MutationProcess(ALPHABET, subst_probs=.2, ge_prob=.15, go_prob=.15)
    M_con = MutationProcess(ALPHABET, subst_probs=.05, ge_prob=.05, go_prob=.05)

    pieces = [rand_seq(ALPHABET, 10000) for _ in range(3)]
    conserved = rand_seq(ALPHABET, 1000)

    S = pieces[0] + conserved + pieces[1] + pieces[2]
    pieces_hom = [M_std.mutate(p)[0] for p in pieces]
    conserved_hom = M_con.mutate(conserved)[0]
    T = pieces_hom[0] + pieces_hom[1] + conserved_hom + pieces_hom[2]

    fig = plt.figure()
    gs = gridspec.GridSpec(1, 2, width_ratios=[30,1])
    ax = plt.subplot(gs[0])
    ax_colorbar = plt.subplot(gs[1])

    cmap = plt.cm.get_cmap('jet')

    print 'finding homologies'
    HF = HomologyFinder(S, T, **HF_kw)
    scores = []
    for segment, score, match_prob in HF.similar_segments(K):
        (d_min, d_max), (a_min, a_max) = segment
        print segment, score, match_prob
        color = cmap(match_prob)[:3]
        plot_similar_segment(ax, segment, color=color)
        scores.append(score)

    norm = matplotlib.colors.Normalize(vmin=0, vmax=1)
    plot_seeds(ax, HF.seeds(), len(S), len(T))
    adjust_pw_plot(ax, len(S), len(T))

    cb1 = matplotlib.colorbar.ColorbarBase(ax_colorbar, cmap=cmap, norm=norm, orientation='vertical')

    fig.tight_layout()
    fig.savefig('conserved-sequences.png', dpi=300) # NOTE LOCAL ALIGNMENT WORKS !!! (Wed, 17 Jan 2018)

# M is the mutation process to insert noise to each read, note that when
# comparing two reads later they have both suffered mutations at the rate
# dictated by M and hence are "twice" furhter apart as they are from the
# original genome.
def create_simulated_reads(M, path='reads_sim.fa', genome_size=10000,
                           read_len=2000, num_reads=40):
    print 'simulating sequencing reads for genome %d bp and %d reads of %d bp.' % \
        (genome_size, num_reads, read_len)
    genome = rand_seq(ALPHABET, genome_size)
    indic = ProgressIndicator(num_total=num_reads)
    indic.start()
    for read, start in rand_read(genome, len_mean=read_len, num=num_reads):
        indic.progress()
        reads.append(M.mutate(read)[0])
        mappings.append((start, start + len(read)))
    indic.finish()

    with open(path, 'w') as f:
        f.write('\n'.join('> + %d:%d\n%s' % (m[0], m[1], str(read)) for m, read in zip(mappings, reads)))

def load_mapped_reads(path, max_num=100):
    reads, mappings = [], []
    print 'loading sequencing reads from %s' % path
    count = 0
    with open(path) as f:
        while True:
            line = f.readline()
            if not line:
                break
            rc, coordinates = line[2:].split()
            assert rc in '+-'
            m0, m1 = coordinates.split(':')
            mappings.append((rc, int(m0), int(m1)))
            reads.append(ALPHABET.parse(f.readline().strip()))
            count += 1
            if count == max_num:
                break
    return reads, mappings

def exp_overlap_detection():
    # NOTE when mutation probabilities for HF are lower than that of actual
    # mutaions we don't see any of the overlaps! (which is good). Also note
    # that since we are mutation both reads the HF and mutation probabilities
    # are significantly different.
    mut_gap = .08
    mut_subst = .05
    M = MutationProcess(ALPHABET, subst_probs=mut_subst, ge_prob=mut_gap, go_prob=mut_gap)
    #create_simulated_reads(M, 'reads_sim.fa')

    wordlen = 8
    log_level = logging.WARN
    kmer_cache_db_path = 'overlaps.db'
    seed_index_path = ':memory:'
    seed_index_path = 'overlaps.db'

    KC_kw = {'alphabet': ALPHABET, 'wordlen': wordlen, 'path': kmer_cache_db_path, 'log_level': log_level}
    kmer_cache = KmerCache(**KC_kw)

    hf_gap = .15
    hf_subst = .15
    HF_kw = {'gap_prob': hf_gap, 'subst_prob': hf_subst, 'sensitivity': .9, 'kmer_cache': kmer_cache}
    HF_kw.update(**KC_kw)
    HF_kw['path'] = seed_index_path

    # ========================
    #reads, mappings = load_mapped_reads('reads_sim.fa')
    #db_path = 'experiment.db'
    #reads, mappings = load_mapped_reads('reads_real.fa')

    #def _overlaps(map0, map1):
        #rc0, from0, to0 = map0
        #rc1, from1, to1 = map1
        #if rc0 != rc1:
            #return False
        #overlap_len = min(to0, to1) - max(from0, from1)
        #if overlap_len > 10:
            #return True
        #else:
            #return False

    #scores = {
        #'s0_pos': [],
        #'s0_neg': [],
        #'s1_pos': [],
        #'s1_neg': [],
    #}
    #num_reads = len(reads)
    #assert len(reads) == len(mappings)
    #num_total = (num_reads * (num_reads - 1)) / 2
    #print 'finding all overlapping pairs of reads'
    #indic = ProgressIndicator(num_total=num_total, percentage=False)
    #indic.start()
    #for i, j in combinations(range(num_reads), 2):
        #indic.progress()
        #HF = HomologyFinder(reads[i], reads[j], **HF_kw)
        #seeds = list(HF.seeds())
        #(seg0, s0), (seg1, s1) = HF.highest_scoring_overlap_band()
        ##fig = plt.figure()
        ##ax = fig.add_subplot(1, 1, 1)
        ##len0, len1 = len(reads[i]), len(reads[j])
        ##plot_seeds(ax, HF.seeds(), len0, len1)
        ##adjust_pw_plot(ax, len0, len1)
        ##fig.tight_layout()
        #if _overlaps(mappings[i], mappings[j]):
            #scores['s0_pos'].append(s0)
            #scores['s1_pos'].append(s1)
            ##print '+', i, j, reads[i].content_id[:8], reads[j].content_id[:8], '#%d,' % len(seeds), round(s0, 2), round(s1, 2)
            ##fig.savefig('seeds/+%s_%s.png' % (reads[i].content_id[:8], reads[j].content_id[:8]), dpi=300)
        #else:
            #scores['s0_neg'].append(s0)
            #scores['s1_neg'].append(s1)
            ##print '-', i, j, reads[i].content_id[:8], reads[j].content_id[:8], '#%d,' % len(seeds), round(s0, 2), round(s1, 2)
            ##fig.savefig('seeds/-%s_%s.png' % (reads[i].content_id[:8], reads[j].content_id[:8]), dpi=300)

    #indic.finish()
    # =========================

    #pickle_dump('overlap_scores.txt', scores, 'H0/H1 overlap detection scores')
    #scores = pickle_load('overlap_scores.txt')

    #pickle_dump('overlap_scores[real].txt', scores, 'H0/H1 overlap detection scores')
    scores = pickle_load('overlap_scores[real].txt')

    #from plots import plot_density
    #fig = plt.figure()
    #ax = fig.add_subplot(1, 1, 1)
    #plot_density(ax, scores['s1_neg'], c='r')
    #plot_density(ax, scores['s1_pos'], c='g')
    #fig.savefig('density_debug.png', dpi=300)
    #raise

    #plot_classifier(scores['s0_pos'], scores['s0_neg'], 'H0', 'blot', kmer_cache.log, classifier='>')
    #plot_classifier(scores['s1_pos'], scores['s1_neg'], 'H1', 'blot', kmer_cache.log, classifier='>')
    labels = ['overlapping', 'non-overlapping']
    plot_classifier(scores['s0_pos'], scores['s0_neg'], name='H0_overlap_real',
                    labels=labels)
    plot_classifier(scores['s1_pos'], scores['s1_neg'], name='H1_overlap_real',
                    labels=labels)

if __name__ == '__main__':
    #exp_stats_performance()
    exp_local_alignment()
    #exp_conserved_sequences()
    #exp_overlap_detection()
