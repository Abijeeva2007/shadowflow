// Shared TypeScript shapes of the backend API responses.

export interface Summary {
  total_txns: number;
  n_accounts: number;
  n_edges: number;
  n_banks: number;
  date_range: [string, string];
  flagged_rings: number;
  flagged_accounts: number;
  alerts_before: number;
  alerts_after: number;
  accounts_filtered_benign: number;
  false_alarms_before: number;
  false_alarms_after: number;
  precision_recall: Record<
    string,
    {
      before_filter: Prf;
      after_filter: Prf;
    }
  >;
  decoy_checks: Record<
    string,
    { label: string; flagged: boolean; n_pattern_hits: number }
  >;
  rings_in_ground_truth: number;
  // funnel: raw alerts -> benign filter -> reviewed -> confirmed ring accounts
  accounts_total: number;
  reviewed: number;
  ring_accounts: number;
}

export interface Prf {
  tp: number;
  fp: number;
  fn: number;
  precision: number;
  recall: number;
  f1: number;
}

export interface Ring {
  ring_id: string;
  type: string;
  score: number;
  n_accounts: number;
  accounts: string[];
  banks: string[];
  amount: number;
  start: string;
  end: string;
  txn_count: number;
  sparkline: number[];
}

export interface CyElement {
  data: {
    id: string;
    label?: string;
    source?: string;
    target?: string;
    bank?: string;
    kind?: string;
    risk?: number;
    degree?: number;
    roles?: string[];
    amount?: number;
    time?: string;
    channel?: string;
  };
}

export interface RingGraph {
  ring_id: string;
  type: string;
  score: number;
  window: [string, string];
  elements: CyElement[];
}

export interface Velocity {
  txn_count: number;
  txns_per_hour: number;
  peak_burst_rate: number;
  pass_through_ratio: number;
  median_hold_min: number;
  amount_mean: number;
  amount_max: number;
}

export interface AccountDetail {
  account: string;
  bank: string;
  risk_score: number;
  pattern_score: number | null;
  anomaly_score: number | null;
  reasons: string[];
  velocity: Velocity;
  fingerprint: Record<string, unknown>;
  benign: boolean;
  filter_reason: string | null;
  burst_timeline: { time: string; count: number }[];
  in_rings: string[];
}

export interface TraceNode {
  parent: string | null;
  txn_id: string;
  src: string;
  dst: string;
  time: string;
  amount: number;
  taint_amount: number;
  taint_fraction: number;
  depth: number;
}

export interface TraceResult {
  root_txn: string | null;
  root_account: string;
  root_time: string;
  root_amount: number;
  total_traced: number;
  n_hops: number;
  terminals: Record<string, number>;
  tree: TraceNode[];
  events: string[];
}

export interface FrontierPoint {
  label: string;
  params: {
    hop_delay_hours: number;
    n_splits: number;
    jitter: number;
    n_decoys: number;
    n_banks: number;
  };
  detected: boolean;
  evidence: string;
  cost_hours: number;
  fee_pct: number;
  extra_accounts: number;
  friction: number;
}

export interface AdversaryResult {
  baseline_detected: boolean;
  n_schemes_tested: number;
  cheapest_evader: {
    label: string;
    detected: boolean;
    friction: number;
    cost_hours: number;
    fee_pct: number;
    extra_accounts: number;
    params: FrontierPoint["params"];
  } | null;
  friction_before: number;
  friction_after: number;
  hardened_thresholds: Record<string, number>;
  frontier: FrontierPoint[];
}

export interface FedCase {
  case_id: string;
  banks: string[];
  pattern_types: string[];
  n_accounts: number;
  hashed_ids: string[];
  window_start: string;
  window_end: string;
  amount_bucket: string;
  n_signals: number;
}

export interface FederationSignals {
  banks: string[];
  n_signals: number;
  signals: {
    bank: string;
    hashed_id: string;
    pattern_type: string;
    direction: string;
    window: [string, string];
    amount_bucket: string;
    pattern_score: number;
  }[];
  cases: FedCase[];
}

export interface RevealResult {
  revealed: boolean;
  hashed_id?: string;
  account_id?: string;
  banks?: string[];
  authorised_by?: string;
  reason?: string;
  note?: string;
}

export interface VerifyResult {
  ring_id: string;
  chain_valid: boolean;
  n_records: number;
  current_final_hash: string;
  dossier_on_file: boolean;
  exported_final_hash?: string;
  matches_export?: boolean;
}
