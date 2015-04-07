# -*- coding: utf-8 -*-

"""Cluster store."""

#------------------------------------------------------------------------------
# Imports
#------------------------------------------------------------------------------

import os
import os.path as op

import numpy as np

from ...utils.array import _is_array_like, _index_of
from ...utils._misc import _concatenate_dicts
from ...utils.logging import info
from ...io.h5 import open_h5
from ...io.sparse import load_h5, save_h5
from ...ext.six import string_types


#------------------------------------------------------------------------------
# Data stores
#------------------------------------------------------------------------------

class MemoryStore(object):
    """Store cluster-related data in memory."""
    def __init__(self):
        self._ds = {}

    def store(self, cluster, **data):
        """Store cluster-related data."""
        if cluster not in self._ds:
            self._ds[cluster] = {}
        self._ds[cluster].update(data)

    def load(self, cluster, keys=None):
        """Load cluster-related data."""
        if keys is None:
            return self._ds.get(cluster, {})
        else:
            if isinstance(keys, string_types):
                return self._ds.get(cluster, {}).get(keys, None)
            assert isinstance(keys, (list, tuple))
            return {key: self._ds.get(cluster, {}).get(key, None)
                    for key in keys}

    @property
    def clusters(self):
        """List of cluster ids in the store."""
        return sorted(self._ds.keys())

    def delete(self, clusters):
        """Delete some clusters from the store."""
        assert isinstance(clusters, list)
        for cluster in clusters:
            if cluster in self._ds:
                del self._ds[cluster]

    def clear(self):
        """Clear the store completely by deleting all clusters."""
        self.delete(self.clusters)


class DiskStore(object):
    """Store cluster-related data in HDF5 files."""
    def __init__(self, directory):
        assert directory is not None
        self._directory = op.realpath(directory)

    # Internal methods
    # -------------------------------------------------------------------------

    def _cluster_path(self, cluster):
        """Return the absolute path of a cluster in the disk store."""
        # TODO: subfolders
        rel_path = '{0:05d}.h5'.format(cluster)
        return op.realpath(op.join(self._directory, rel_path))

    def _cluster_file_exists(self, cluster):
        """Return whether a cluster file exists."""
        return op.exists(self._cluster_path(cluster))

    def _cluster_file(self, cluster, mode):
        """Return a file handle of a cluster file."""
        path = self._cluster_path(cluster)
        return open_h5(path, mode)

    # Data get/set methods
    # -------------------------------------------------------------------------

    def _get(self, f, key):
        """Return the data for a given key."""
        path = '/{0:s}'.format(key)
        if f.exists(path):
            return load_h5(f, path)
        else:
            return None

    def _set(self, f, key, value):
        """Set the data for a given key."""
        path = '/{0:s}'.format(key)
        save_h5(f, path, value, overwrite=True)

    # Public methods
    # -------------------------------------------------------------------------

    def store(self, cluster, **data):
        """Store cluster-related data."""
        with self._cluster_file(cluster, 'a') as f:
            for key, value in data.items():
                self._set(f, key, value)

    def load(self, cluster, keys=None):
        """Load cluster-related data."""
        # The cluster doesn't exist: return None for all keys.
        if not self._cluster_file_exists(cluster):
            if keys is None:
                return {}
            elif isinstance(keys, string_types):
                return None
            elif isinstance(keys, list):
                return {key: None for key in keys}
            else:
                raise ValueError(keys)
        # Create the output dictionary.
        out = {}
        # Open the cluster file in read mode.
        with self._cluster_file(cluster, 'r') as f:
            # If a single key is requested, return the value.
            if isinstance(keys, string_types):
                return self._get(f, keys)
            # All keys are requested if None.
            if keys is None:
                keys = f.datasets()
            assert isinstance(keys, (list, tuple))
            # Fetch the values for all requested keys.
            for key in keys:
                out[key] = self._get(f, key)
        return out

    @property
    def clusters(self):
        """List of cluster ids in the store."""
        if not op.exists(self._directory):
            return []
        files = os.listdir(self._directory)
        clusters = [int(op.splitext(file)[0]) for file in files]
        return sorted(clusters)

    def delete(self, clusters):
        """Delete some clusters from the store."""
        for cluster in clusters:
            if self._cluster_file_exists(cluster):
                os.remove(self._cluster_path(cluster))

    def clear(self):
        """Clear the store completely by deleting all clusters."""
        self.delete(self.clusters)


#------------------------------------------------------------------------------
# Store
#------------------------------------------------------------------------------

class Store(object):
    """Wrap a MemoryStore and a DiskStore."""

    def __init__(self, store_path=None):
        # Create the memory store.
        self._memory_store = MemoryStore()

        # Create the disk store.
        if store_path is not None:
            self._disk_store = DiskStore(store_path)
        else:
            self._disk_store = None

        # Where the info are stored: a {'field' => ('memory' or 'disk')} dict.
        self._dispatch = {}

    def register_field(self, name, location):
        """Register a field to be stored either in 'memory' or on 'disk'."""
        self._check_location(location)
        self._dispatch[name] = location

    def _check_location(self, location):
        """Check that a location is valid."""
        if location not in ('memory', 'disk'):
            raise ValueError("'location 'should be 'memory' or 'disk'.")

    def _filter(self, keys, location):
        """Return all keys registered in the specified location."""
        if keys is None:
            return None
        else:
            return [key for key in keys
                    if self._dispatch.get(key, None) == location]

    # Public methods
    # -------------------------------------------------------------------------

    @property
    def clusters(self):
        """Return the list of clusters present in the store."""
        # TODO: rename to cluster_ids for consistency?
        clusters_memory = self._memory_store.clusters
        if self._disk_store is None:
            return clusters_memory
        clusters_disk = self._disk_store.clusters
        # Both stores should have the same clusters at all times.
        if clusters_memory != clusters_disk:
            raise RuntimeError("Cluster store inconsistency.")
        return clusters_memory

    def store(self, cluster, location=None, **data):
        """Store cluster-related information."""

        # If the location is specified, register the fields there.
        if location in ('memory', 'disk'):
            for key in data.keys():
                self.register_field(key, location)
        elif location is not None:
            self._check_location(location)

        # Store data in memory.
        data_memory = {k: data[k] for k in self._filter(data.keys(), 'memory')}
        self._memory_store.store(cluster, **data_memory)

        # Store data on disk.
        if self._disk_store is not None:
            data_disk = {k: data[k] for k in self._filter(data.keys(), 'disk')}
            self._disk_store.store(cluster, **data_disk)

    def load(self, cluster, keys=None):
        """Load cluster-related information."""
        if isinstance(keys, string_types):
            if self._dispatch[keys] == 'memory':
                return self._memory_store.load(cluster, keys)
            elif self._dispatch[keys] == 'disk':
                return self._disk_store.load(cluster, keys)
        elif keys is None or isinstance(keys, list):
            data_memory = self._memory_store.load(cluster,
                                                  self._filter(keys, 'memory'))
            if self._disk_store is not None:
                data_disk = self._disk_store.load(cluster,
                                                  self._filter(keys, 'disk'))
            else:
                data_disk = {}
            return _concatenate_dicts(data_memory, data_disk)
        else:
            raise ValueError("'keys' should be a list or a string.")

    def clear(self):
        """Clear the cluster store."""
        self._memory_store.clear()
        if self._disk_store is not None:
            self._disk_store.clear()

    def delete(self, clusters):
        """Delete all information about the specified clusters."""
        self._memory_store.delete(clusters)
        if self._disk_store is not None:
            self._disk_store.delete(clusters)


#------------------------------------------------------------------------------
# Cluster store
#------------------------------------------------------------------------------

class ClusterStore(object):
    def __init__(self, model=None, path=None):
        self._model = model
        self._spikes_per_cluster = {}
        self._store = Store(path)
        self._items = []

    @property
    def spikes_per_cluster(self):
        return self._spikes_per_cluster

    def register_item(self, item_cls):
        """Register a StoreItem instance in the store."""

        # Instanciate the item.
        item = item_cls(model=self._model, store=self._store)
        assert item.fields is not None

        for name, location in item.fields:
            if location in ('memory', 'disk'):
                # Register the storage location for that item.
                self._store.register_field(name, location)

                # Create the load function for that item.

                # HACK: need to use a factory function because in Python
                # functions are closed over names, not values. Here we
                # want 'name' to refer to the 'name' local variable.
                def _make_func(name):
                    return lambda cluster: self._store.load(cluster, name)

                load = _make_func(name)

            else:
                raise ValueError("The 'location' should be 'memory', 'disk'"
                                 ".")

            # We create the self.<name>(cluster) method for loading.
            # We need to ensure that the method name isn't already attributed.
            assert not hasattr(self, name)
            setattr(self, name, load)

        # Register the StoreItem instance.
        self._items.append(item)

    def load(self, name, clusters, spikes):
        assert _is_array_like(clusters)
        assert np.all(np.in1d(clusters, self._store.clusters))
        # Concatenation of arrays for all clusters.
        arrays = np.concatenate([self._store.load(cluster, name)
                                 for cluster in clusters])
        # Concatenation of spike indices for all clusters.
        spike_clusters = np.concatenate([self._spikes_per_cluster[cluster]
                                         for cluster in clusters])
        assert np.all(np.in1d(spikes, spike_clusters))
        idx = _index_of(spikes, spike_clusters)
        return arrays[idx, ...]

    def update(self, up):
        # TODO: update self._spikes_per_cluster
        # Delete the deleted clusters from the store.
        self._store.delete(up.deleted)
        if up.description == 'merge':
            self.merge(up)
        elif up.description == 'assign':
            self.assign(up)
        else:
            raise NotImplementedError()

    def merge(self, up):
        for item in self._items:
            item.merge(up)

    def assign(self, up):
        for item in self._items:
            item.assign(up)

    def generate(self, spikes_per_cluster):
        """Populate the cache for all registered fields and the specified
        clusters."""
        assert isinstance(spikes_per_cluster, dict)
        clusters = sorted(spikes_per_cluster.keys())
        self._spikes_per_cluster = spikes_per_cluster
        # self._store.delete(clusters)
        if hasattr(self._model, 'name'):
            name = self._model.name
        else:
            name = 'the current model'
        info("Generating the cluster store for {0:s}...".format(name))
        for item in self._items:
            for cluster in clusters:
                info("Loading {0:s}, cluster {1:d}...".format(item.name,
                     cluster))
                item.store_from_model(cluster, spikes_per_cluster[cluster])
        info("Done!")


class StoreItem(object):
    """A class describing information stored in the cluster store.

    Attributes
    ----------
    fields : list
        A list of pairs (field_name, storage_location).
        storage_location is either 'memory', 'disk'.
    model : Model
        A Model instance for the current dataset.
    store : ClusterStore
        The ClusterStore instance for the current dataset.

    Methods
    -------
    store_from_model(cluster, spikes)
        Extract some data from the model and store it in the cluster store.
    assign(up)
        Update the store when the clustering changes.
    merge(up)
        Update the store when a merge happens (by default, it is just
        an assign, but this method may be overriden for performance reasons).

    """
    fields = None  # list of (field_name, storage_location)
    name = 'item'

    def __init__(self, model=None, store=None):
        self.model = model
        self.store = store

    def merge(self, up):
        """May be overridden."""
        self.assign(up)

    def assign(self, up):
        """May be overridden. No need to delete old clusters here."""
        for cluster in up.added:
            self.store_from_model(cluster, up.new_spikes_per_cluster[cluster])

    def store_from_model(self, cluster, spikes):
        """May be overridden. No need to delete old clusters here."""
        pass
