export function getDataFreshnessChangeCount(state) {
  if (!state) {
    return 0;
  }
  return (
    state.changedCount ||
    state.addedCount ||
    state.removedCount ||
    state.updatedCount ||
    state.invalidCount ||
    state.affectedVolunteerIds?.length ||
    state.affectedUnitIds?.length ||
    0
  );
}

export function hasDataFreshnessChangeSummary(state) {
  if (!state) {
    return false;
  }
  if (getDataFreshnessChangeCount(state) > 0) {
    return true;
  }
  const summary = state.summary || '';
  return summary.startsWith('招生计划数据已变化') || summary.startsWith('检测到高途招生计划源数据有更新');
}

export function hasDetailedDataFreshnessChangeSummary(state) {
  if (!state) {
    return false;
  }
  if (getDataFreshnessChangeCount(state) > 0) {
    return true;
  }
  const summary = state.summary || '';
  return summary.startsWith('招生计划数据已变化');
}

export function shouldShowDataFreshnessNotice(state) {
  return Boolean(
    state?.statusCode === 'changed' &&
      state?.shouldNotify !== false &&
      hasDetailedDataFreshnessChangeSummary(state)
  );
}

export function resolveCandidateRefreshMode(state) {
  if (state?.statusCode !== 'changed' || !state?.requiresCandidateRefresh) {
    return 'none';
  }
  return hasDetailedDataFreshnessChangeSummary(state) ? 'local_query' : 'source_sync';
}
