# -*- coding: utf-8 -*-
"""
.. wikisection:: overview
    :title: (5) Seeds (exactly matching kmers)

    The :mod:`biseqt.seeds` module provides tools for storing and analyzing
    exactly matching kmers, aka seeds.

    >>> from biseqt.seeds import SeedIndex
    >>> from biseqt.sequence import Sequence, Alphabet
    >>> A = Alphabet('ACGT')
    >>> S, T = A.parse('TAAGCGT'), A.parse('GGCGTAA')
    >>> seed_index = SeedIndex(S, T, path=':memory:', wordlen=3, alphabet=A)
    >>> list(seed_index.seeds())
    [(4, 2), (3, 1), (0, 4)]
"""
from itertools import chain, combinations
from itertools import groupby, product

from .kmers import KmerIndex, KmerDBWrapper


class SeedIndex(KmerDBWrapper):
    """An index for seeds in diagonal coordinates.

    Attributes:
        S (biseqt.sequence.Sequence): The 1st sequence.
        T (biseqt.sequence.Sequence): The 2nd sequence.
        cache (KmerCache): optional :class:`KmerCache` object to use for
            retrieving integer representations of sequences.
    """
    def __init__(self, S, T, kmer_cache=None, **kw):
        name = '%s_%s' % (S.content_id[:8], T.content_id[:8])
        super(SeedIndex, self).__init__(name=name, **kw)
        self.kmer_cache = kmer_cache
        self.self_comp = S == T
        self.S, self.T = S, T
        self.d0 = len(self.T) - 1
        if self._table_exists():
            self.log('seeds for %s and %s already indexed, skipping' %
                     (S.content_id[:8], T.content_id[:8]))
        else:
            self.log('Indexing seeds for %s (%d) and %s (%d).' %
                     (S.content_id[:8], len(S), T.content_id[:8], len(T)))
            self._index_seeds()

    @property
    def seeds_table(self):
        """The seeds table name ``seeds_[name]``, cf.
        :attr:`KmerDBWrapper.name`."""
        return 'seeds_' + self.name

    @classmethod
    def to_diagonal_coordinates(cls, i, j):
        """Convert standard coordinates to diagonal coordinates via:

        .. math::
            \\begin{aligned}
                d & = i - j \\\\
                a & = \min(i, j)
            \\end{aligned}
        """
        d = i - j
        a = min(i, j)
        return d, a

    @classmethod
    def to_ij_coordinates(cls, d, a):
        """Convert diagonal coordinates to standard coordinates:

        .. math::
            \\begin{aligned}
                i & = a + max(d, 0) \\\\
                j & = a - min(d, 0)
            \\end{aligned}
        """
        i = a + max(d, 0)
        j = a - min(d, 0)
        return (i, j)

    @classmethod
    def to_ij_coordinates_seg(cls, seg):
        """Convert a segment in diagonal coordinates to standard coordinates
        according to :func:`to_ij_coordinates`.

        Args:
            seg (tuple): :math:`(d_{min}, d_{max}), (a_{min}, a_{max})`
        """
        corners = [cls.to_ij_coordinates(d, a) for d, a in product(*seg)]
        i_start = min(i for i, _ in corners)
        j_start = min(j for _, j in corners)
        i_end = max(i for i, j in corners)
        j_end = max(j for _, j in corners)
        return (i_start, i_end), (j_start, j_end)

    def _table_exists(self):
        with self.connection() as conn:
            q = """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='%s';
            """ % self.seeds_table
            cursor = conn.cursor()
            cursor.execute(q)
            for name in cursor:
                return True
        return False

    # idempotent operation
    def _index_seeds(self):
        with self.connection() as conn:
            conn.cursor().execute("""
                CREATE TABLE %s (
                  'd_' INTEGER,     -- zero-adjusted diagonal position
                  'a'  INTEGER      -- antidiagonal position
                );
            """ % self.seeds_table)

        kmer_index_name = '%d_%s' % (self.wordlen, self.name)
        kmer_index = KmerIndex(path=self.path, name=kmer_index_name,
                               wordlen=self.wordlen, alphabet=self.alphabet,
                               log_level=self.log_level, mask=self.mask,
                               kmer_cache=self.kmer_cache)
        kmer_index.index_kmers(self.S)
        if not self.self_comp:
            kmer_index.index_kmers(self.T)

        kmers = kmer_index.kmers()

        def _records():
            for kmer in kmers:
                hits = kmer_index.hits(kmer)
                if self.self_comp:
                    pairs = chain(combinations(hits, 2),
                                  [(x, x) for x in hits])
                else:
                    pairs = (((id0, pos0), (id1, pos1))
                             for (id0, pos0), (id1, pos1)
                             in combinations(hits, 2)
                             if id0 != id1)
                for (id0, pos0), (id1, pos1) in pairs:
                    d, a = self.to_diagonal_coordinates(pos0, pos1)
                    yield d + self.d0, a

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                'INSERT INTO %s (d_, a) VALUES (?, ?)' % self.seeds_table,
                _records()
            )
            # FIXME is this necessary?
            self.log('Creating SQL index for table %s.' % self.seeds_table)
            cursor.execute('CREATE INDEX %s_diagonal ON %s(d_);' %
                           (self.seeds_table, self.seeds_table))

    def seeds(self, d_band=None, exclude_trivial=False):
        """Yields all seeds, optionally those within a diagonal band.

        Keyword Args:
            d_band (tuple|None):
                If specified a ``(d_min, d_max)`` tuple restricting the seed
                count to a diagonal band.

        Yields:
            tuple:
                seeds coordinates :math:`(i, j)`.
        """
        query = 'SELECT d_, a FROM %s' % self.seeds_table
        if d_band is not None:
            assert len(d_band) == 2, 'need a 2-tuple for diagonal band'
            d_min, d_max = d_band
            query += ' WHERE d_ - %d BETWEEN %d AND %d ' % \
                (self.d0, d_min, d_max)
        query += ' ORDER BY rowid'

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            for d_, a in cursor:
                i, j = self.to_ij_coordinates(d_ - self.d0, a)
                if self.self_comp and exclude_trivial and i == j:
                    continue
                yield (i, j)
                if self.self_comp and i != j:
                    yield (j, i)

    def seed_count(self, d_band=None, a_band=None):
        """Counts the number of seeds either in the whole table or in the
        specified diagonal band.

        Args:
            d_band (tuple|None):
                If specified a ``(d_min, d_max)`` tuple restricting the seed
                count to a diagonal band.

        Returns:
            int: Number of seeds found in the entire table or in the specified
            diagonal band.
        """
        query = 'SELECT COUNT(*) FROM %s' % self.seeds_table
        conds = []
        if d_band is not None:
            assert len(d_band) == 2, 'need a 2-tuple for diagonal band'
            d_min, d_max = d_band
            cond = 'd_ - %d BETWEEN %d AND %d' % \
                   (self.d0, d_min, d_max)
            conds.append(cond)

        if a_band is not None:
            assert len(a_band) == 2, 'need a 2-tuple for antidiagonal band'
            conds.append('a BETWEEN %d AND %d' % a_band)

        if conds:
            query += ' WHERE ' + ' AND '.join(conds)

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            for row in cursor:
                return row[0]
            return 0


class SeedIndexMultiple(KmerDBWrapper):
    """An index for seeds between multiple sequences in diagonal coordinates.

    Attributes:
        seqs (list[biseqt.sequence.Sequence]): The sequences of interest.
        cache (KmerCache): optional :class:`KmerCache` object to use for
            retrieving integer representations of sequences.
    """
    def __init__(self, *seqs, **kw):
        assert(len(seqs)) > 2
        name = '_'.join(S.content_id[:8] for S in seqs)
        super(SeedIndexMultiple, self).__init__(name=name, **kw)
        self.kmer_cache = kw.get('kmer_cache', None)
        self.self_comp = len(seqs) == 2 and seqs[0] == seqs[1]
        self.seqs = seqs
        self.d0s = [len(T) - 1 for T in seqs[1:]]

        if self._table_exists():
            self.log('Seeds for %s already indexed, skipping' % name)
        else:
            self.log('Indexing seeds for %s.' % name)
            self._index_seeds()

    @property
    def seeds_table(self):
        """The seeds table name ``seeds_[name]``, cf.
        :attr:`KmerDBWrapper.name`."""
        return 'seeds_' + self.name

    @classmethod
    def to_diagonal_coordinates(cls, *idxs):
        """Convert standard coordinates to diagonal coordinates via:

        .. math::
            \\begin{aligned}
                d_k & = i_1 - i_{k+1} \ \ k = 1, 2, \ldots, n - 1 \\\\
                a & = \min(i_1, \ldots, i_n)
            \\end{aligned}
        """
        ds = [idxs[0] - idxs[k] for k in range(1, len(idxs))]
        a = min(idxs)
        return ds, a

    @classmethod
    def to_ij_coordinates(cls, ds, a):
        """Convert diagonal :math:`(d_1,\ldots, d_{n-1}, a)` coordinates to
        standard coordinates via:

        .. math::
            i_k = a - min\{d_0, -d_1, \ldots, -d_{n-1}\} + d_{k-1}

        where :math:`d_0` is defined for the purpose of the above formula to be
        zero.
        """
        idxs_ = [0] + [-d for d in ds]
        diff = a - min(idxs_)
        idxs = [diff + idx for idx in idxs_]
        return tuple(idxs)

    @classmethod
    def to_ij_coordinates_seg(cls, seg):
        """Convert a segment in diagonal coordinates to standard coordinates
        according to :func:`to_ij_coordinates`.

        Args:
            seg (tuple): :math:`(d_{min}, d_{max}), (a_{min}, a_{max})`
        """
        ds_range, a_range = seg
        num_seqs = len(ds_range) + 1
        seg_flat = ds_range + [a_range]
        corners = [cls.to_ij_coordinates(ranges[:-1], ranges[-1])
                   for ranges in product(*seg_flat)]
        std_ranges = []
        for idx in range(num_seqs):
            std_ranges.append((
                min(corner[idx] for corner in corners),
                max(corner[idx] for corner in corners)
            ))
        return std_ranges

    def _table_exists(self):
        with self.connection() as conn:
            q = """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='%s';
            """ % self.seeds_table
            cursor = conn.cursor()
            cursor.execute(q)
            for name in cursor:
                return True
        return False

    # idempotent operation
    def _index_seeds(self):
        with self.connection() as conn:
            conn.cursor().execute("""
                CREATE TABLE %s (
                  'ds' VARCHAR,     -- comma separated diagonal positions
                  'a'  INTEGER      -- antidiagonal position
                );
            """ % self.seeds_table)

        kmer_index_name = '%d_%s' % (self.wordlen, self.name)
        kmer_index = KmerIndex(path=self.path, name=kmer_index_name,
                               wordlen=self.wordlen, alphabet=self.alphabet,
                               log_level=self.log_level,
                               kmer_cache=self.kmer_cache)
        if self.self_comp:
            kmer_index.index_kmers(self.seqs[0])
        else:
            for seq in self.seqs:
                kmer_index.index_kmers(seq)

        kmers = kmer_index.kmers()

        def _records():
            for kmer in kmers:
                if kmer is None:
                    continue
                hits = kmer_index.hits(kmer)
                hits = {seqid: [c[1] for c in seq_hits]
                        for seqid, seq_hits in groupby(hits,
                                                       key=lambda c: c[0])}
                # only consider kmers present in all sequences
                if len(hits) < len(self.seqs):
                    continue
                # FIXME deal with self_comp: let 1 argument mean self_comp not
                # two identical sequences.
                for idxs in product(*hits.values()):
                    # NOTE we're storing d values and not d_
                    ds, a = self.to_diagonal_coordinates(*idxs)
                    yield ','.join(str(d) for d in ds), a

        with self.connection() as conn:
            cursor = conn.cursor()
            query = 'INSERT INTO %s (ds, a) VALUES (?, ?)' % self.seeds_table
            cursor.executemany(query, _records())
            self.log('Creating SQL index for table %s.' % self.seeds_table)
            cursor.execute('CREATE INDEX %s_diagonal ON %s(ds);' %
                           (self.seeds_table, self.seeds_table))

    def seeds(self):
        """Yields all seeds in diagonal coordinates.

        Yields:
            tuple:
                seeds coordinates :math:`(d_1, \ldots, d_{n-1}, a)`.
        """
        query = 'SELECT ds, a FROM %s' % self.seeds_table
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            for ds, a in cursor:
                ds = [int(i) for i in ds.split(',')]
                yield ds, a
