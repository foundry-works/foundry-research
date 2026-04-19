# LLM Confidence in Binary Classification: Methods, Calibration, and Implications for Human-AI Routing

## Executive Summary

This report synthesizes 23 deeply read academic sources on methods for measuring LLM confidence in binary classification tasks, calibration quality across model families, and the relationship between LLM confidence and human inter-rater uncertainty. The findings are organized around seven research questions, with emphasis on method tradeoffs (Q3), LLM-human comparison (Q4), and adversarial critique (Q5), as these are most relevant to a planned study of confidence-based routing in math scoring.

Three confidence elicitation paradigms dominate the literature -- logprob-based, verbalized, and consistency-based -- and the central finding is that **the optimal method depends critically on whether the model has undergone RLHF alignment**. Pre-trained logprobs are well-calibrated (ECE (Expected Calibration Error -- lower is better, 0.0 is perfect) near 0.01 for 52B models). Instruction tuning degrades this calibration significantly, but applying RLHF afterward stabilizes rather than worsens it [2][10]. For RLHF-tuned models, verbalized confidence paradoxically reduces ECE by 30-50% relative to logprobs [2]. Consistency-based methods (especially semantic entropy) achieve the best discriminative accuracy (AUROC (a measure of how well the confidence score separates correct from incorrect answers; 1.0 is perfect, 0.5 is chance) 0.83 vs. 0.75 for logprobs and 0.65 for verbalized) but at 5-10x computational cost [4][5]. No single method dominates all dimensions.

On the comparison between LLM and human confidence -- the question most relevant to routing -- the evidence is sobering. LLM confidence correlates with human agreement on easy, unanimous items (r=0.81) but drops to r=0.23 on items where humans disagree [25]. LLMs exhibit fundamentally flatter difficulty-sensitivity curves than humans, maintaining ~0.8-0.9 confidence regardless of whether actual accuracy is 20% or 90%, though GPT-4o shows greater difficulty sensitivity than LLaMA-3-70B or Claude-3 [7]. Confidence is manipulable by 20-40 percentage points via persona prompts without any change in accuracy [7]. These findings indicate that confidence-based routing is feasible but requires empirical threshold tuning on domain-specific calibration data -- naive reliance on raw confidence scores will route poorly on exactly the items (ambiguous, hard) where routing matters most.

Standard calibration metrics have well-documented blind spots: ECE is sensitive to binning and blind to miscalibration direction, AUROC ignores calibration entirely, and Brier score conflates calibration with sharpness [5][19][9]. The planned study should report multiple complementary metrics.

## 1. Confidence Elicitation Methods

### 1.1 Logprob-Based Methods

Logprob methods extract confidence from the model's token-level probability distribution -- via softmax probability on the predicted answer, sequence entropy, or normalized likelihood [5][2]. For binary classification, this reduces to examining the probability mass on "Yes"/"No" or equivalent tokens.

Kadavath et al. introduced P(True), where the model evaluates its own generated answer, using the probability of the "True" token as confidence. Their 52B model achieved ECE near 0.01 on multiple-choice benchmarks [1]. A related method, P(IK) ("probability that I know"), trains a value head (binary classifier) on top of the language model's final-token representations, optionally with full model finetuning [1]. It reaches AUROC of 0.864 on in-distribution tasks but fails severely out-of-distribution -- AUROC drops to 0.606 on the Lambada benchmark [1].

**Key limitation:** Logprob access is unavailable for many commercial APIs (GPT-4, Claude), and RLHF fine-tuning degrades calibration by collapsing distributions toward high-reward behaviors [2][10]. This makes logprobs unreliable for the most capable deployed models.

**Evidence strength:** Strong (multiple independent primary studies with consistent findings).

### 1.2 Verbalized Confidence

Verbalized methods ask the model to express a numerical confidence score (0-100%) or linguistic hedging as output tokens [2][5][11]. This works with any API-accessible model.

For RLHF-tuned models, verbalized confidence is paradoxically better-calibrated than logprobs. On TriviaQA, verbalized confidence achieves ECE of 0.053 versus label probability ECE of 0.097 for GPT-3.5-turbo -- a 45% reduction [2][1]. Models at 70B+ parameters achieve ECE around 0.07-0.10 with optimized prompting using a "combo" method (probability-scoring formulation + advanced description + few-shot examples) [20]. Multiple-hypothesis verbalization (asking for top-k guesses before confidence) improves ECE by 45-64% [2].

A large-scale study across 80 models found that Linguistic Verbal Uncertainty (LVU) -- inferring confidence from natural hedging language like "probably" and "might" rather than explicit numerical scores -- outperforms both token-based and numerical verbalized methods by approximately 10% in both AUROC and ECE (as reported by the authors) [12].

**Key limitation:** Highly prompt-sensitive (ECE ranges 0.53-0.95 across formulations for small models) [12][11]. Models below 7B parameters show near-zero correlation between verbalized confidence and correctness [12]. Complex prompting that helps large models actively degrades small models [11].

**Evidence strength:** Strong (large-scale comparative studies across multiple model families).

### 1.3 Consistency-Based Methods

Consistency methods sample multiple responses and compute agreement as a confidence proxy. Semantic entropy -- clustering semantically equivalent responses via bidirectional NLI (Natural Language Inference -- a technique for checking whether two statements have the same meaning) and computing entropy over meaning-clusters -- achieves AUROC of 0.83 on TriviaQA versus 0.75 for standard entropy and 0.65 for P(True) [4][5]. The advantage grows with model size: incorrect answers generate roughly 2x more semantic clusters than correct ones [4].

Self-consistency (vote-counting across samples) achieves ECE of 0.3830 on HotpotQA but requires 10-100 samples per query [14]. A survey of 150+ methods estimates multi-sample approaches cost over $12,000 per million queries for trillion-parameter LLMs while yielding at most 0.02 AUROC improvement over well-tuned single-pass alternatives [11].

**Evidence strength:** Strong for semantic entropy (ICLR 2023 with extensive ablations). Moderate for cost-efficiency claims (single survey).

### 1.4 Training-Based and Hybrid Methods

Four training-based approaches have shown calibration improvements:

- **SaySelf** combines supervised fine-tuning with RL using a quadratic reward, achieving ECE of 0.3558 on HotpotQA versus 0.6667 for direct prompting -- with single-pass inference. The RL stage is critical: without it, calibration degrades on 5 of 6 datasets [14][23].
- **CritiCal** trains student models via teacher-generated natural language critiques, reducing ECE from 0.283 to 0.221 on StrategyQA and sometimes outperforming the teacher [12][16].
- **SteerConf** steers confidence via multi-level prompting, reducing ECE from 41.8% to 20.7% on GPT-3.5 [17][5].
- **Reflection-based prompting** (evaluate, reflect, conclude) approaches fine-tuned probe performance without fine-tuning (AUPRC 0.890 vs. 0.910) [18].

**Evidence strength:** Moderate (individual papers, limited cross-study replication).

## 2. Calibration Quality Across Models

### 2.1 Scale Effects

Calibration improves with model scale on classification tasks: ECE decreases consistently from 800M to 52B parameters across BIG-Bench, MMLU, and TruthfulQA [1]. This holds when models are in the under-fitted regime; once performance saturates, larger scale can increase calibration error [22]. However, high accuracy and reliable uncertainty estimation are independent capabilities. Models with >85% accuracy may exhibit ECE >0.3, while moderately accurate models (~67%) can achieve top-tier uncertainty estimation [12]. Qwen3-235B in reasoning mode achieves only 67% accuracy yet delivers best-in-class uncertainty across all methods [12]. This decoupling means selecting the most accurate model does not guarantee the best-calibrated confidence.

Pre-trained language models do not learn to become well-calibrated through fine-tuning: confidence increases monotonically regardless of prediction correctness, with ECE increasing monotonically in the over-fitted regime [22]. This suggests that standard fine-tuning cannot be relied on to produce well-calibrated models. Learnable calibration methods -- which train a separate model to predict when the main model is correct -- significantly outperform traditional post-hoc approaches like temperature scaling (a technique that rescales model output probabilities without retraining the model) [22][19].

Small models (7B and below) show severe degradation: ECE values of 0.30-0.64 for verbalized confidence, with complex prompting strategies that benefit large models actively harming small ones [12][11].

### 2.2 The RLHF Calibration Paradox

Pre-trained models produce well-calibrated logit probabilities, but alignment training systematically degrades this [10][2]. Instruction tuning causes the most pronounced degradation, while RLHF applied afterward stabilizes but does not improve calibration [10]. Instruction data diversity matters critically: synthetic homogeneous data (Alpaca) causes severe degradation while diverse human-labeled data (OpenAssistant) is less harmful [10]. Parameter-efficient methods like LoRA (Low-Rank Adaptation -- fine-tuning a small fraction of model weights rather than retraining the entire model) preserve calibration better than full fine-tuning [10].

This creates a practical paradox: the models most useful for deployment (instruction-tuned, RLHF-aligned) are precisely those whose logprobs are least reliable. Verbalized confidence partially resolves this, as RLHF apparently teaches models social norms around expressing uncertainty even while degrading internal probability calibration [2][1].

### 2.3 Reasoning-Enhanced Models

Reasoning-enhanced models (e.g., Qwen3-Think) improve calibration by 20%+ in ECE and reduce overconfident predictions (>90% confidence) by over 20% [12]. Remarkably, 4B-parameter models with reasoning capability match or exceed the calibration of much larger models like GPT-4.1 [12], suggesting reasoning architecture enables better uncertainty estimation independent of scale.

### 2.4 Task-Dependent Calibration

Calibration varies dramatically by task. Reasoning tasks (math, physics) achieve AUROC approximately 10 points higher than knowledge-heavy tasks (law, philosophy) [12]. On hard factual benchmarks (SimpleQA), even GPT-4o achieves only 35% accuracy with ECE of 0.45, while on easier benchmarks (TriviaQA) it reaches 90% accuracy with ECE of 0.07 [15]. Probabilistic alignment drops from 67% (ChatGPT on NQ) to 13% on low-frequency questions, while verbalized confidence shows less variability across question types [6][5][12].

**Implication for math scoring:** The finding that reasoning tasks produce better-calibrated uncertainty is encouraging for the planned study, though no paper specifically addresses educational scoring.

## 3. Method Tradeoffs: Which Approach for Binary Educational Scoring?

### 3.1 The Core Disagreement

The literature contains a genuine disagreement about method superiority:

- **Ni et al.** find probabilistic confidence (logprobs) more accurate than verbalized, with 61-67% alignment versus 45-52% on open-domain QA [6]. Probabilistic methods require in-domain validation to set optimal thresholds.
- **Tian et al.** find verbalized confidence outperforms logprobs for RLHF models, reducing ECE by ~50% [2]. However, they estimated logprob calibration via sampling (n=10) for closed-source models, effectively weakening the logprob baseline.
- **Kuhn et al.** advocate semantic entropy for superior accuracy despite cost [4].

**Resolution:** The disagreement dissolves once RLHF status and API access are accounted for. For pre-trained or base models with logprob access, probabilistic methods are preferred. For RLHF-aligned API models without logprob access, verbalized methods are the better option [2][6][4].

### 3.2 Domain-Dependent Method Suitability

Task domain significantly affects which method works best. Logit-based methods face limitations because low token probabilities reflect "multiple linguistic properties, not just confidence" [5]. For binary classification or multiple-choice tasks -- the format closest to math scoring -- verbalized and logit methods are sufficient [5][6]. Semantic entropy excels primarily for open-ended QA, where semantic equivalence between responses complicates evaluation [5][6][12].

Model architecture and training regime fundamentally alter method effectiveness. Instruction tuning degrades logprob calibration while RLHF maintains it [10]. LoRA mitigates calibration damage better than full fine-tuning [10]. Reasoning-enhanced models improve uncertainty across all three methods [12]. GPT-4V shows superior self-awareness versus Gemini Pro Vision despite comparable architecture [9], indicating fine-tuning choices shape confidence reliability. **Method choice must co-optimize with model selection** rather than treating confidence elicitation as model-agnostic [10][12][9].

### 3.3 The Shifting Cost-Efficiency Frontier

Hybrid and training-based approaches increasingly outperform pure prompting. SaySelf achieves ECE of 0.3558 on HotpotQA versus self-consistency's 0.3830, with single-pass inference matching the efficiency of methods requiring 100 forward passes [14]. Hybrid approaches combining low-cost proxies (attention variance, hidden-state clustering) for initial filtering with targeted multi-sampling on high-risk outputs achieve approximately 90% of peak performance at 10% computational cost [11].

Calibration-improving methods address method limitations differently. Multiple-hypothesis verbalization improves ECE by 45-64% [2]. Focal loss (a training objective that emphasizes hard-to-classify examples) for auxiliary models outperforms standard binary cross-entropy loss (BCE) 3:1 [19]. UF Calibration decomposes confidence into Uncertainty + Fidelity, improving MMLU ECE from 0.120 to 0.088 [26]. Post-hoc and training-based refinements can substantially close gaps between methods, though base method choice remains foundational [2][19][26].

### 3.4 Expert Consensus and Practical Decision Tree

No single method dominates all dimensions: logprobs for white-box precision, verbalized for API-accessible simplicity, consistency-based for maximum accuracy when budget allows [4][6][2][15][19]. For the planned binary math scoring study:

1. **If logprobs are available** (open-source model or API exposing them): Use logprobs with post-hoc temperature scaling or focal-loss calibration [19][3]. Watch for RLHF degradation.
2. **If logprobs are unavailable** (commercial API): Use optimized verbalized confidence with the "combo" prompt (probability-scoring + advanced description + 5-shot examples) [20]. Expect ECE ~0.07-0.15 for 70B+ models.
3. **If maximum accuracy is needed regardless of cost:** Layer semantic entropy or self-consistency on top, budgeting 5-10x inference cost [4][5].
4. **Emerging alternative:** Training-based methods (SaySelf, CritiCal) achieve single-pass efficiency rivaling consistency methods but require fine-tuning access [14][12].

**Evidence strength for domain-specific recommendations:** Moderate. No study specifically addresses binary educational/math scoring with confidence elicitation. Recommendations are extrapolated from QA and classification benchmarks.

## 4. LLM Confidence vs. Human Uncertainty

### 4.1 The Correlation Exists but Is Weak

Across 12 LLMs on offensive language detection (10,753 samples, 5 annotators per item), model confidence-agreement correlation drops sharply from 0.81 on unanimous items to 0.23 on items with human disagreement [25]. Models maintain high self-consistency (Cohen's kappa > 0.75) even on weakly-agreed items where they achieve only 57% accuracy [25][7]. Training on disagreement samples improves calibration (MSE from 0.1856 to 0.1075 for LLaMA3-8B) but does not resolve the fundamental issue: models struggle to lower confidence on items humans find ambiguous [25].

At the individual-sample level, probabilistic and verbalized confidence show Spearman correlation of only 0.13-0.38, suggesting the two modalities access fundamentally different information sources [6][20]. In aggregate (bin-level), probabilistic confidence shows near-perfect correlation with accuracy (0.89-1.00) while verbalized shows moderate correlation (0.45-0.92) [6] -- suggesting probabilistic confidence is reliable for estimating system-level accuracy but unreliable for per-item routing decisions.

### 4.2 Fundamentally Different Difficulty-Sensitivity

LLMs exhibit flatter confidence curves across difficulty levels compared to human Dunning-Kruger patterns [7]. Humans show overconfidence on hard tasks and underconfidence on easy tasks with clear difficulty sensitivity. LLMs instead maintain relatively constant confidence (~0.8-0.9) regardless of whether actual accuracy is 20% or 90% [7][9]. This flatness is most pronounced in LLaMA-3-70B and Claude-3; GPT-4o shows greater difficulty sensitivity, though still less than humans [7]. This means LLMs will not naturally flag the hard items that most need human review -- their confidence signal is weakest precisely where routing decisions are most consequential.

### 4.3 Persona Manipulability Without Accuracy Change

LLM confidence shifts by 20-40 percentage points when models adopt occupational personas ("expert" vs. "layperson"), without any change in actual accuracy [7]. Demographic personas produce stereotypical biases (Asian > other races; Male > Female in confidence) without accuracy differences [7]. This reveals that LLM confidence depends on prompt-surface social cues rather than knowledge assessment, fundamentally unlike human confidence which -- despite its own biases -- is grounded in actual experience and knowledge.

### 4.4 The Ground-Truth Problem

Using human agreement as ground truth is complicated by the fact that humans themselves demonstrate poor confidence calibration on ambiguous tasks [15]. When annotators show weak agreement (3/5 agree), they are implicitly expressing uncertainty through disagreement, yet majority-vote ground-truth labels treat such cases as definitive targets [15]. This effectively asks models to be overconfident about genuinely ambiguous instances -- a structural problem that no elicitation method can fully resolve.

Human confidence varies with question frequency and familiarity: higher alignment between confidence and accuracy on less frequent questions [6]. Human raters exhibit persona-based confidence biases analogous to LLM vulnerabilities, expressing different confidence levels depending on perceived social role despite identical accuracy [7].

Neither humans nor LLMs naturally separate genuine epistemic uncertainty from social confidence signaling -- a structural similarity that complicates routing designs that assume one is a reliable proxy for the other.

### 4.5 Prompt Engineering Shapes the Alignment

Auxiliary model-based calibration shows 25% lower sensitivity to prompt variation compared to native LLM probabilities (ECE variance 1.65x vs. 2.2x across prompts) [19]. Few-shot prompts are most effective for maintaining calibration across accuracy variations, while verbalized confidence degrades as accuracy drops [19]. The method for eliciting confidence fundamentally shapes whether uncertainty can reliably track human-like patterns.

### 4.6 Implications for Routing in Math Scoring

A simulation study demonstrated that confidence-threshold delegation yields substantial accuracy gains: with optimal threshold tau=0.70, team accuracy reaches 84.1% versus 77.7% for AI alone or 71.9% for humans alone [21]. However, this study is simulation-only: human behavior was modeled via a mathematical formula rather than measured empirically, and AI confidence was assumed uniformly distributed rather than drawn from a real LLM [21]. It also assumes well-calibrated confidence and independent errors, neither of which holds in practice.

**Practical recommendation:** The weak correlation on disputed items (r=0.23) means the routing threshold must be set conservatively, using domain-specific calibration data from a held-out set of items with known human agreement levels. The flat difficulty-sensitivity curves mean that if confidence does not differentiate items humans find easy from items they find hard, the routing signal will be too weak for reliable use.

**Evidence strength:** Moderate (3 direct comparison papers, none in educational contexts). No studies specifically compare LLM confidence to human scorer disagreement in math scoring -- this is a genuine literature gap.

## 5. Adversarial Perspective: Is LLM Confidence Meaningful?

### 5.1 Token Statistics, Not Epistemic Uncertainty

Multiple convergent lines of evidence suggest LLM confidence reflects surface-level token statistics rather than genuine task uncertainty:

- **Flat difficulty curves:** Models maintain 0.8-0.9 confidence across tasks with 20-90% actual accuracy, with LLaMA-3-70B and Claude-3 most affected and GPT-4o somewhat less so [7][9].
- **Persona manipulation:** Confidence shifts by 20-40 percentage points with persona prompts while accuracy remains unchanged [7].
- **Weak cross-modal correlation:** Probabilistic and verbalized confidence correlate at only rho=0.13-0.38 at the sample level, indicating they access different information sources -- neither reliably representing epistemic uncertainty [6][20].
- **None-of-the-above failure:** Replacing a multiple-choice option with "none of the above" degrades calibration to ECE >0.3, indicating models assess relative confidence between presented options rather than absolute probability of correctness [1].
- **Accuracy-uncertainty independence:** Models with >90% accuracy can have ECE >0.3, while 67%-accurate models can achieve ECE <0.08 [12]. Confidence is not a byproduct of correct answer generation but a distinct, separately learned mechanism.

### 5.2 RLHF Breaks the Logprob-Correctness Link

Pre-trained models' logits reflect corpus frequency statistics and are well-calibrated [1], but RLHF collapses probability distributions toward high-reward behaviors [1][2][10]. Instruction tuning degrades logprob calibration more than RLHF itself: Alpaca (synthetic, homogeneous) causes severe degradation while OpenAssistant (human-labeled, diverse) is less harmful [10]. The logprob-correctness relationship established during pretraining is broken by alignment training and cannot be recovered by simple post-hoc adjustment [10].

### 5.3 Overconfidence as a Systematic Failure

Nominal 99% confidence intervals cover true answers only 65% of the time in Fermi estimation tasks -- a 34-point gap [23]. Coverage plateaus rather than improving with higher nominal targets, consistent with a "perception tunnel" effect: models access a truncated slice of their true probability distribution and treat it as complete [23].

On ambiguous classification items (human agreement A0), LLMs maintain Cohen's kappa > 0.75 while achieving only 57% accuracy [7][25]. Models show rigid confidence assignment regardless of human disagreement levels -- they fail to recognize genuine task ambiguity [7][25].

### 5.4 Confidence Decouples from Accuracy Under Distribution Shift

P(IK) trained on TriviaQA produces "terrible" calibration on Lambada (out-of-distribution), with AUROC dropping from 0.864 to 0.606 and Brier score nearly tripling [1]. Larger models paradoxically show increased miscalibration on easier tasks despite accuracy gains: GPT-4o's ECE increases from 0.071 to 0.083 on TriviaQA when distractor options are added, despite modest accuracy improvements [15]. These findings demonstrate that confidence does not track genuine knowledge -- a model can become more accurate while its self-assessed certainty becomes less reliable.

### 5.5 The Distractor Paradox

Providing structured distractors (converting free-response to multiple-choice) dramatically improves both accuracy (up to 460%) and calibration (ECE reductions up to 90%) on hard benchmarks, but paradoxically **worsens calibration on easy tasks** for large RLHF models [15][23]. This effect has no analogue in human uncertainty and further suggests that LLM confidence reflects task framing rather than epistemic state.

**Evidence strength:** Strong (convergent evidence from 6+ independent studies across different tasks and model families).

## 6. Calibration Metric Limitations

### 6.1 ECE: Widely Used, Deeply Flawed

Expected Calibration Error has critical limitations [5][11][19]:

- **Binning sensitivity:** Results vary significantly with bin count, width, and equal-mass vs. equal-width schemes. M=10, M=20, M=100 yield different values for the same model, making inter-study comparison unreliable without standardization [5][19].
- **Directional blindness:** ECE uses absolute differences, masking whether a model is overconfident or underconfident. Net Calibration Error (NCE) addresses this with signed differences [9].
- **Gameable:** ECE can be reduced by simply lowering all confidence scores (via temperature scaling), improving the metric while degrading utility for selective prediction [19][11].
- **Protocol dependence:** Different implementations (full vocabulary softmax vs. constrained A-D tokens vs. length-normalized) produce substantially different model rankings on MMLU [5].

### 6.2 AUROC: Discrimination Without Calibration

AUROC measures discriminative power but is insensitive to calibration. A model can achieve high AUROC while being severely miscalibrated [12][11]. ECE and AUROC correlations are weak (Kendall tau = 0.23-0.30), confirming calibration and discrimination are independent dimensions requiring separate evaluation [12].

### 6.3 Brier Score: Conflated Dimensions

Brier score conflates calibration and sharpness. Optimizing for low Brier score can produce models that assign constant confidence (e.g., always 0.75 when accuracy is 0.75) -- technically calibrated but uninformative for distinguishing individual predictions [9][11][24].

### 6.4 Metrics That Misalign with Human Disagreement

Standard metrics (ECE, AUROC, Brier) do not align with human annotation variation: calibration optimized for binary correctness can misalign with inherent task ambiguity where humans themselves disagree [5][16]. A unified evaluation benchmark is missing from the field, making cross-study comparison unreliable [5][11].

### 6.5 Recommendations for the Planned Study

Report multiple metrics simultaneously: ECE (with specified binning), AUROC, and Brier decomposition at minimum. Include directional metrics (NCE or signed error) to distinguish overconfidence from underconfidence [9]. Report informativeness measures (number of distinct values, variance) to detect constant-estimator problems. Use reliability diagrams to visualize per-bin patterns that aggregate metrics obscure.

**Evidence strength:** Strong (consistent critique across multiple methodological papers and surveys).

## 7. Human Calibration Biases

Humans exhibit systematic miscalibration that complicates their use as ground-truth benchmarks [7][15][6]:

- **Dunning-Kruger patterns:** Overconfidence on hard tasks, underconfidence on easy tasks, with confidence highly dependent on task difficulty [7]. LLMs lack this difficulty-sensitivity, making the two uncertainty patterns structurally different.
- **Persona-based biases:** Both humans and LLMs express different confidence levels depending on perceived social role, despite identical accuracy [7].
- **Annotation disagreement as implicit uncertainty:** When annotators show weak agreement (3/5), they express uncertainty through disagreement, but standard ground-truth labels treat majority votes as definitive [15]. This embeds overconfidence into the evaluation framework itself.
- **Frequency effects:** Human confidence varies with question familiarity [6].

**Evidence strength:** Moderate. Current coverage relies on LLM-focused papers that discuss human biases secondarily. Foundational human calibration literature (Lichtenstein et al. 1982) was unavailable due to paywalls.

## Limitations & Open Questions

1. **No educational scoring studies.** No paper in the reviewed literature specifically examines LLM confidence calibration for math or educational scoring tasks. All recommendations are extrapolated from QA, classification, and factual knowledge benchmarks. The transferability to scoring rubric-based binary judgments is untested.

2. **Thin human-LLM comparison evidence.** Direct comparison between LLM confidence and human inter-rater disagreement is covered by only 3 papers, none in educational contexts. The correlation of r=0.23 on disputed items comes from offensive language detection and may not generalize.

3. **Human calibration literature gap.** Classic psychology literature on overconfidence in binary judgment (Lichtenstein et al. 1982, Keren 1991) was behind paywalls. Coverage relies on secondary discussion within LLM papers.

4. **Rapidly evolving field.** Several cited papers are 2025 preprints. Reasoning-enhanced models and training-based calibration methods are emerging rapidly; recommendations may shift as these mature.

5. **Binary vs. continuous confidence.** Most studies elicit continuous confidence scores (0-100%). The binary classification setting may interact differently with elicitation methods, particularly for logprob-based approaches where the binary token distribution is simpler.

6. **Weak individual-item signal.** The correlation between confidence and correctness at the individual-item level (rho = 0.13-0.38) means per-item routing will have substantial error rates even with well-calibrated aggregate confidence [6].

## Methodology

### Search Strategy

This review was conducted through 30+ searches across 7 providers: Semantic Scholar (16 searches), Linkup (2), arXiv (2), OpenAlex (2), Perplexity (2), PubMed (2), plus Exa, GenSee, and CORE. Tavily was unavailable; Perplexity, Linkup, and Exa served as web-search fallbacks. The searches yielded 486 unique sources after deduplication.

Seven citation traversals were conducted: references from "Can LLMs Express Their Uncertainty" (Ni et al.), "Just Ask for Calibration" (Tian et al.), and the Geng et al. 2024 survey; cited-by from "Can LLMs Express," the Geng survey, and Guo et al. 2017. Two cited-by traversals returned 0 results. Citation traversal on "Taming Overconfidence in LLMs" yielded 20 cited-by results.

### Source Acquisition and Quality

From 486 deduplicated sources, 64 were downloaded for content review. After quality filtering:
- **23 sources deeply read** and validated by reader agents (on-topic with good evidence)
- **7 abstract-only stubs** (insufficient content for deep reading)
- **10 degraded PDFs** (unreadable after conversion)
- **4 content mismatches** (src-069, src-295, src-344, src-236 -- content did not match metadata)
- **2 web stubs/form pages**

### Coverage Assessment

76 findings were logged across all 7 questions (Q1: 17, Q2: 16, Q3: 9, Q4: 5, Q5: 13, Q6: 10, Q7: 6). All questions have 5+ findings from 2+ deeply read sources.

- **Q1-Q3 and Q5** (methods, calibration, tradeoffs, adversarial): Strong coverage (8-10+ sources each)
- **Q4** (LLM-human comparison): Moderate (3 direct comparison papers)
- **Q6** (metrics): Moderate (4 sources with detailed analysis)
- **Q7** (human calibration): Thin-to-moderate (2 direct sources; PubMed searches returned clinical prediction papers rather than cognitive science)

### Gap-Resolution Decision

After logging 76 findings, additional gap-mode searches were not pursued because remaining gaps (Q4 educational scoring, Q7 classic psychology) represent genuine literature gaps rather than search coverage gaps. No papers specifically comparing LLM confidence to human scorer disagreement in educational contexts appear to exist. The human calibration classics are behind paywalls.

### Cross-Source Contradictions

Three key contradictions were identified and resolved:
1. **Ni et al. vs. Tian et al.** on probabilistic vs. verbalized superiority: resolved by RLHF status (see Section 3.1).
2. **Chhikara** finds distractor prompts reduce ECE up to 90% but paradoxically worsen calibration on easy tasks for large RLHF models -- both findings confirmed; the paradox is real.
3. **Kadavath** finds larger models well-calibrated (ECE ~0.01); **Chen et al.** [22] find PLMs do not learn calibration through fine-tuning. Resolution: very large pretrained models are well-calibrated, but fine-tuning/alignment degrades this.

## References

[1] Kadavath, S., Conerly, T., Askell, A., Henighan, T., Drain, D., Perez, E., et al. "Language Models (Mostly) Know What They Know." Anthropic, 2022. https://arxiv.org/pdf/2207.05221.pdf

[2] Tian, K., Mitchell, E., Zhou, A., Sharma, A., Rafailov, R., Yao, H., Finn, C., Manning, C.D. "Just Ask for Calibration: Strategies for Eliciting Calibrated Confidence Scores from Language Models Fine-Tuned with Human Feedback." Harvard / Stanford, 2023. https://arxiv.org/pdf/2305.14975.pdf

[3] Lin, S., Hilton, J., Evans, O. "Teaching Models to Express Their Uncertainty in Words." University of Oxford / OpenAI, 2022. https://arxiv.org/pdf/2205.14334.pdf

[4] Kuhn, L., Gal, Y., Farquhar, S. "Semantic Uncertainty: Linguistic Invariances for Uncertainty Estimation in Natural Language Generation." ICLR 2023. University of Oxford. https://arxiv.org/pdf/2302.09664.pdf

[5] Geng, J., Cai, F., Wang, Y., Koeppl, H., Nakov, P., Gurevych, I. "A Survey of Confidence Estimation and Calibration in Large Language Models." MBZUAI / TU Darmstadt, 2024. https://arxiv.org/pdf/2311.08298.pdf

[6] Ni, S., Bi, K., Yu, L., Guo, J. "Are Large Language Models More Honest in Their Probabilistic or Verbalized Confidence?" ICT, CAS, 2024. https://arxiv.org/pdf/2408.09773.pdf

[7] Xu, C., Wen, B., Han, B., Wolfe, R., Wang, L.L., Howe, B. "Do Language Models Mirror Human Confidence? Exploring Psychological Insights to Address Overconfidence in LLMs." Findings of ACL 2025. University of Washington / Allen Institute for AI. https://aclanthology.org/2025.findings-acl.1316.pdf

[9] Groot, T., Valdenegro-Toro, M. "Overconfidence is Key: Verbalized Uncertainty Evaluation in Large Language and Vision-Language Models." University of Groningen, 2024. http://arxiv.org/pdf/2405.02917.pdf

[10] Zhu, C., Xu, B., Wang, Q., Zhang, Y., Mao, Z. "On the Calibration of Large Language Models and Alignment." USTC / BUPT, 2023. https://arxiv.org/pdf/2311.13240.pdf

[11] Liu, X., Chen, T., Da, L., Chen, C., Lin, Z., Wei, H. "Uncertainty Quantification and Confidence Calibration in Large Language Models: A Survey." Arizona State University / U. of Chicago / UIUC, 2025. https://xiao0o0o.github.io/2025KDD_tutorial/survey.pdf

[12] Tao, L., Yeh, Y.-F., Dong, M., Huang, T., Torr, P., Xu, C. "Revisiting Uncertainty Estimation and Calibration of Large Language Models." University of Sydney / City University of Hong Kong / SJTU / Oxford, 2025. http://www.arxiv.org/pdf/2505.23854.pdf

[13] Ren, J.J., Luo, J., Zhao, Y., Krishna, K., Saleh, M., Lakshminarayanan, B., Liu, P.J. "Out-of-Distribution Detection and Selective Generation for Conditional Language Models." ICLR, 2022. DOI: 10.48550/arxiv.2209.15558

[14] Xu, T., Wu, S., Diao, S., Liu, X., Wang, X., Chen, Y., Gao, J. "SaySelf: Teaching LLMs to Express Confidence with Self-Reflective Rationales." Purdue / UIUC / USC / NVIDIA, 2024. https://arxiv.org/pdf/2405.20974.pdf

[15] Chhikara, P. "Mind the Confidence Gap: Overconfidence, Calibration, and Distractor Effects in Large Language Models." Transactions on Machine Learning Research, 2025. University of Southern California. https://arxiv.org/pdf/2502.11028.pdf

[16] Zong, Q., Liu, J., Zheng, T., Li, C., Xu, B., Shi, H., Wang, W., Wang, Z., Chan, C., Song, Y. "CritiCal: Can Critique Help LLM Uncertainty or Confidence Calibration?" HKUST, 2025. https://arxiv.org/pdf/2510.24505.pdf

[17] Zhou, Z., Jin, T., Shi, J., Li, Q. "SteerConf: Steering LLMs for Confidence Elicitation." Hong Kong Polytechnic University / NUS, 2025. https://arxiv.org/pdf/2503.02863.pdf

[18] Bodhwani, U., Ling, Y., Dong, S., Feng, Y., Li, H., Goyal, A. "A Calibrated Reflection Approach for Enhancing Confidence Estimation in LLMs." Amazon, 2024. https://assets.amazon.science/a8/ee/bfc47294433da5fdba0a65159ecd/a-calibrated-reflection-approach-for-enhancing-confidence-estimation-in-llms.pdf

[19] Xia, Y., Luz de Araujo, P.H., Zaporojets, K., Roth, B. "Influences on LLM Calibration: A Study of Response Agreement, Loss Functions, and Prompt Styles." University of Vienna / Aarhus University, 2025. DOI: 10.48550/arxiv.2501.03991

[20] Yang, D., Tsai, Y.-F.H., Yamada, M. "On Verbalized Confidence Scores for LLMs." ETH Zurich, 2024. https://www.researchgate.net/publication/387264282_On_Verbalized_Confidence_Scores_for_LLMs

[21] Ibrahim, M. "Confidence-Based Trust Calibration in Human-AI Teams." International Journal of Advanced Computer Science and Applications, 2025. DOI: 10.14569/ijacsa.2025.01612122

[22] Chen, Y., Yuan, L., Cui, G., Liu, Z., Ji, H. "A Close Look into the Calibration of Pre-trained Language Models." UIUC / HUST / Tsinghua, 2022. https://arxiv.org/pdf/2211.00151.pdf

[23] Epstein, E.L., Winnicki, J., Sornwanee, T., Dwaraknath, R. "LLMs are Overconfident: Evaluating Confidence Interval Calibration with FermiEval." Stanford University, 2025. https://arxiv.org/pdf/2510.26995.pdf

[24] Groot, T. "Uncertainty Estimation in Large Language Models." Bachelor's thesis, University of Groningen, 2024. https://fse.studenttheses.ub.rug.nl/32044/13/bAI_2024_TobiasGroot.pdf

[25] Lu, Y., et al. "Is LLM an Overconfident Judge? A Study on LLM-as-a-Judge with Annotator Agreement." 2025. https://arxiv.org/abs/2502.06207

[26] Zhang, L., et al. "Calibrating the Confidence of Large Language Models by Eliciting Fidelity." 2024. https://arxiv.org/abs/2404.02655
