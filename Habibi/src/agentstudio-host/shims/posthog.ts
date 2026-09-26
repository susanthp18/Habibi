/**
 * `posthog-js` for the ported screens: product analytics stay on the box.
 * Every call is a no-op; nothing is sent anywhere.
 */
const noop = (..._args: unknown[]): undefined => undefined;

const posthog = {
  __loaded: false,
  init: noop,
  capture: noop,
  identify: noop,
  reset: noop,
  register: noop,
  group: noop,
  setPersonProperties: noop,
  opt_out_capturing: noop,
  isFeatureEnabled: (..._args: unknown[]) => false,
  getFeatureFlag: (..._args: unknown[]): undefined => undefined,
  onFeatureFlags: noop,
};

export default posthog;
