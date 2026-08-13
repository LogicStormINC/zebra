export type TurnDisclosure = "open" | "collapsed";

export type TurnStatus =
  | "running"
  | "succeeded"
  | "waiting_user"
  | "waiting_input"
  | "waiting_approval"
  | "failed"
  | "canceled"
  | "cancelled";

const COLLAPSED_BY_DEFAULT = new Set<TurnStatus>(["succeeded"]);

/**
 * Deterministic turn disclosure default. A running turn stays open so the
 * user watches progress; succeeded turns collapse so finished turns recede;
 * waiting/failed/canceled turns stay open because they need user attention.
 */
export function defaultTurnDisclosure(status: TurnStatus): TurnDisclosure {
  return COLLAPSED_BY_DEFAULT.has(status) ? "collapsed" : "open";
}

export function isTurnCollapsedByDefault(status: TurnStatus): boolean {
  return defaultTurnDisclosure(status) === "collapsed";
}
