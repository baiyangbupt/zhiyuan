const requireAll = (requireContext: __WebpackModuleApi.RequireContext) =>
    requireContext.keys().map(requireContext);

const req = require.context('./svgs', false, /.svg$/);

requireAll(req);
export {}; // 默认到处，ts如若不导出，会警告

