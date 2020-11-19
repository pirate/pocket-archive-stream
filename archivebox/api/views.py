__package__ = 'archivebox.api'

from rest_framework import viewsets, generics, mixins

from core.models import Snapshot
from .serializers import SnapshotSerializer

class SnapshotViewset(viewsets.ReadOnlyModelViewSet):
    queryset = Snapshot.objects.all()
    serializer_class = SnapshotSerializer
