# Neural stock research: evidence, implementation and remaining gates

Research checked on **17 September 2026**. Scope: add a useful, auditable numerical research layer to the existing Zara stock expert. This is neither an investment recommendation nor evidence that a model can profitably trade. Source claims, engineering choices and verified implementation are distinguished below. No foundation-model weights or real market dataset were downloaded.

## Decision

Implement a small multilayer perceptron (MLP) and a causal temporal convolutional network (TCN), alongside zero-return and ridge-regression baselines. Keep learned quantities separate from exact rational currency arithmetic and the existing Prolog risk rules. Forecast distributions describe an uncertain statistical target; they do not acquire order authority.

The rationale is falsifiability and bounded deployment, not a claim that small networks always win. The TCN paper compares convolutional and recurrent architectures across sequence tasks, making causal convolutions a defensible starting point, but does not establish stock-trading profitability [1]. The DLinear paper demonstrates that simple linear models are important forecasting comparators on its evaluated datasets; it does not prove that attention is universally ineffective [2]. The implemented ridge model is a baseline motivated by that lesson, **not an implementation of DLinear**.

## Architecture comparison

| Candidate | Research relevance | This change |
| --- | --- | --- |
| MLP | Nonlinear fixed-window comparator with a small, inspectable state | Implemented: two 16-unit hidden layers, Tanh, three-output quantile head |
| Causal TCN | Left-padded, dilated convolutions support causal sequence processing [1] | Implemented: eight channels, kernel three, dilations 1/2/4, residual SiLU blocks |
| PatchTST | Patches and channel-independent weight sharing provide another way to organize longer forecasting contexts [3] | Researched only; not bundled or benchmarked |
| Temporal Fusion Transformer | Separates static, historical and known-future inputs with gated recurrent/attention components [4] | Researched only; requires a richer correctly timestamped covariate pipeline |
| Chronos-2 | A 120M-parameter foundation model supporting univariate, multivariate and covariate-informed quantile forecasts [5] | Candidate later; no adapter or weights included |
| TimesFM-3 | Google's August 2026 multivariate forecasting release [6] | Not bundled; current official weights declare a non-commercial license [7] |

The current compact TCN has a **15-observation receptive field**, even when a longer input window is configured. The MLP consumes the whole configured window. This limitation is deliberate and documented rather than represented as long-horizon attention. At context 16, the MLP has 595 parameters and the TCN 643. A future dilated-depth change must update the architecture schema, tensor validator and causality tests together.

The Chronos-2 model card currently labels its weights Apache-2.0, unlike the TimesFM-3 weights' named non-commercial license [5,7]. Code licenses and weight licenses must be checked separately before distribution or business use. Neither a vendor benchmark nor a permissive license establishes financial forecasting skill. Any future pretrained model also needs a pinned revision, known precision, resource budget and pretraining-contamination review.

## Data and target definition

The implemented target is `log(adjusted_close[t+h] / adjusted_close[t])`. Inputs contain only previous close-to-close log returns, ending at the forecast origin. Horizon counts **observed expected sessions**, not calendar days. It is not a target-price estimator, a portfolio policy, a tax calculation, an intraday fill model, or a volume/fundamental/news model.

Trusted daily observations must declare currency, source, instrument, adjustment basis, effective time and an expected-session index. Their SQLite recorded time comes from the owner, not from a model-provided historical assertion. Duplicate identities, future records, missing sessions, raw/unknown adjustment, mixed semantics and binary-float prices are rejected. Corrections remain append-only and snapshots respect their knowledge cutoff. Source filtering occurs before the row limit, so other-provider rows cannot push relevant observations out of the requested window.

This does not complete the historical-data provider. The existing GLOBAL_QUOTE integration is not an adjusted daily-history API. Alpha Vantage documents TIME_SERIES_DAILY_ADJUSTED separately, including adjusted closes and split/dividend events, and labels that endpoint premium [8]. The new trusted `ingest_bar` boundary is ready for an authorized adapter; access, pagination, exchange calendars, split/dividend revisions and provider-specific entitlements still need implementation. It would be misleading to treat an unknown-adjustment quote as a training bar.

Even a well-labelled adjusted series obtained today may reflect corrections or corporate actions unavailable at an old forecast origin. The implemented evaluations therefore explicitly say **retrospective snapshot diagnostics**, with `point_in_time_market_backtest=false`. A genuine historical decision replay needs a frozen as-known-then snapshot at every origin, publication/availability timestamps for all covariates, and historical universe membership including delisted assets. Today's constituent list cannot stand in for yesterday's investment universe.

## Validation that can fail

Rows remain chronological. Each expanding fold contains training, validation, calibration and a later 16-sample test block. Horizon-sized gaps ensure the last label used by an earlier block ends strictly before the next block's forecast origin. The scaler is fitted only on the training block. Validation selects the training epoch; calibration chooses interval widening; test observations are not used for either. A final model has a separately recorded training/validation/calibration partition.

Temporal splitting and gap exclusion are standard documented tools [9]; the implementation uses its own small explicit splitter, tested against actual label endpoints. It does not use random train/test shuffling. A regression test changes a future tail value and verifies that earlier fold scalers and weight hashes remain identical. Causality is also tested directly by changing future TCN inputs and comparing earlier outputs.

Each fold reports median absolute error, pinball loss, interval width, empirical coverage, zero-return MAE and ridge MAE. All folds are retained, not only the most favorable one. Aggregate metrics average equal-sized test blocks. There is no automatic model promotion, Sharpe ratio, claimed win rate or Sharpe-based neural selection. Median is not synonymous with expected return.

The training budget is fixed and bounded: seed, architecture, horizon, context, fold count and epochs are recorded; Adam uses fixed learning rate and regularization, gradient clipping and validation early stopping. Model cards record the dataset hash, evidence IDs, fitted scalers, framework/precision and weight hash. Numerical reproducibility is sought within the tested CPU environment; PyTorch explicitly does not guarantee identical results across releases or platforms [10].

The backtest-overfitting literature warns that repeated selection over many candidate strategies can make apparently strong historical performance unreliable [11]. Recording completed models is useful but **not** a multiple-testing correction. This implementation has no complete failed-trial ledger, probability-of-backtest-overfitting calculation, deflated Sharpe ratio or corrected significance test. Those omissions are explicit in evaluation metadata and block any claimed profitability result.

## Quantiles and uncertainty

Both models minimize pinball loss at quantiles 0.1, 0.5 and 0.9. The head represents the median plus positive softplus widths, so lower/median/upper ordering holds by construction. A separate calibration block computes conformity scores `max(lower-y, y-upper, 0)` and uses the finite-sample corrected order statistic to widen the interval.

This is a conservative, widening-only adaptation of split conformalized quantile regression, not a claim to reproduce every CQR experiment. The original CQR coverage theorem assumes exchangeable examples [12]. Chronologically dependent stock returns and distribution shifts do not automatically satisfy that premise. Accordingly the result reports nominal coverage, empirical held-out coverage, interval width and `coverage_guaranteed=false`; “80% interval” never means “80% chance this trade wins.” Sixteen calibration scores are especially limited evidence.

Adaptive conformal inference and later online conformal work address changing distributions with their own update rules and assumptions [13,14]. Those algorithms were researched but **not implemented** here. The current eight-standard-deviation input flag is merely a crude out-of-training-range diagnostic, not ACI, an ensemble disagreement measure, a drift-proof detector or a calibrated crash probability. An abstention retains the forecast as research evidence without converting it into an order or silently clamping it into money math.

## Engineering boundary

The existing Zara-managed mailbox continues to own SQLite. Small JSON requests hand numerical work to one supervised CPU subprocess, rather than blocking the database owner or constructing another expert runtime. The process gets one numerical thread, a bounded deadline and no forwarded stock API credential. Timeout and shutdown terminate it. Input, configuration, tensor shape and result-size contracts are bounded; this is not a hostile-process OS sandbox or a hard memory quota.

The plugin accepts no arbitrary model paths, pickles, custom network classes or remote code. JSON weights must match an allowlisted architecture, parameter count, shape, finite values and content digest before tensor reconstruction. PyTorch's serialization guidance discusses pickle and the limits of restricted weight loading [15]; avoiding that path entirely is practical for these very small networks. A checksum detects content mismatch, not provider authenticity or unauthorized database replacement.

Neural training and forecasting are approval-marked persistent tools. A model can never turn itself into `provider_adapter` quote evidence. Currency-denominated calculations remain in the pre-existing rational engine; ML uses explicitly labelled FP32, with FP64 confined to the ridge diagnostic solve. Prolog continues to explain deterministic trade preflight independently. No broker, autonomous asset selection, order submission, account read, installation or Android execution was added.

## Acceptance evidence and next gates

Tests execute both networks and the real subprocess path on synthetic data, and cover corruption, persistence, correction cutoff, namespace isolation, causal boundaries, timeout, cancellation and exact-money separation. The real-runtime CI additionally exercises StructuredTools, the provider normalizer, SQLite and SWI-Prolog, with HTTP and history fixtures. Synthetic success establishes functioning mechanics, **not market skill**. The included smooth-series diagnostic reports both neural models and the stronger ridge baseline without hiding the neural models' worse result.

Before a paper strategy can be evaluated credibly, complete the adjusted-history adapter and exchange-calendar checks, point-in-time corporate-action data, frozen holdout/universe, complete trial accounting, transaction-cost/fill assumptions and walk-forward paper ledger. Quantile calibration should then be evaluated across assets, horizons and regimes with enough observations. Any execution integration would be a separate explicit feature with authorization and deterministic risk controls; no execution permission follows from installing this module.

## Primary sources

[1] Bai, Kolter and Koltun, sequence-model comparison: https://arxiv.org/abs/1803.01271

[2] Zeng et al., simple linear forecasting benchmarks: https://arxiv.org/abs/2205.13504

[3] Nie et al., PatchTST: https://arxiv.org/abs/2211.14730

[4] Lim et al., Temporal Fusion Transformer: https://arxiv.org/abs/1912.09363

[5] Amazon's Chronos-2 model card, architecture and weight license: https://huggingface.co/amazon/chronos-2 ; technical report: https://arxiv.org/abs/2510.15821

[6] Google Research, TimesFM-3 release, 31 August 2026: https://research.google/blog/timesfm-3-a-zero-shot-foundation-model-for-multivariate-forecasting/

[7] Google's official TimesFM-3 weights and license declaration: https://huggingface.co/google/timesfm-3.0-pytorch

[8] Alpha Vantage, daily adjusted endpoint: https://www.alphavantage.co/documentation/#dailyadj

[9] Scikit-learn TimeSeriesSplit and gap: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html

[10] PyTorch 2.10 reproducibility notes: https://docs.pytorch.org/docs/2.10/notes/randomness.html

[11] Bailey et al., The Probability of Backtest Overfitting: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf

[12] Romano, Patterson and Candes, Conformalized Quantile Regression, Algorithm 1 and Theorem 1: https://arxiv.org/html/1905.03222v1

[13] Gibbs and Candes, Adaptive Conformal Inference Under Distribution Shift: https://arxiv.org/abs/2106.00170

[14] Gibbs and Candes, Conformal Inference for Online Prediction with Arbitrary Distribution Shifts: https://arxiv.org/abs/2208.08401

[15] PyTorch 2.10 serialization semantics: https://docs.pytorch.org/docs/2.10/notes/serialization.html
