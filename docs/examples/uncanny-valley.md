# The Uncanny Valley: Evidence, Mechanisms, and Psychology

## Executive Summary

The uncanny valley -- Masahiro Mori's 1970 hypothesis that near-human entities elicit a non-linear dip in affinity -- is one of the most studied yet least agreed-upon phenomena in perception science. After five decades of research involving hundreds of studies, the field has reached a paradoxical state: the core prediction receives remarkably little direct support when rigorously tested, yet the concept clearly captures something real about human perception.

The strongest evidence, from Mathur and Reichling's study of 80 real robot faces, demonstrates a robust cubic valley function that replicates across controlled and pre-registered paradigms. At the same time, the first systematic review (Katsyri et al., 2015) found that only 1 of 8 studies testing the naive uncanny valley hypothesis detected the predicted non-linear effect. The resolution of this paradox lies in specificity: the uncanny valley is not a universal consequence of human-likeness, but emerges reliably under specific conditions -- particularly when perceptual features send conflicting signals about an entity's category.

The theoretical landscape has fragmented into nine competing accounts. The strongest empirical support favors configural processing and perceptual mismatch theories, which predict the most effects in direct head-to-head comparisons. The most popular account -- categorization ambiguity -- is surprisingly weak: multiple studies now demonstrate a dissociation between categorization difficulty and eeriness. Five key contradictions define the current state of the field:

1. The effect occurs for entirely non-human stimuli.
2. Movement does not amplify it as Mori predicted.
3. The full affective response does not emerge until age 9 (though some perceptual sensitivity appears earlier).
4. It is attenuated by embodied experience.
5. Competing models disagree on whether uncanniness involves adding mind to machines or subtracting it.

A critical caveat: the core evidence base is drawn almost entirely from US/Canadian MTurk and undergraduate samples, limiting generalizability.

---

## 1. Introduction: Mori's Original Hypothesis

In 1970, Masahiro Mori, a robotics professor at the Tokyo Institute of Technology, published a short essay in an obscure Japanese journal called *Energy* proposing a deceptively simple idea. He observed that as robots become more humanlike, people's sense of affinity (*shinwakan*) toward them does not increase smoothly. Instead, it rises to an initial peak at moderate human-likeness (toy robots), plunges into a "valley" of negative affect at near-human appearance (prosthetic hands), and then recovers at full human resemblance [1]. Mori presented this not as experimental data but as a personal observation drawn from his experience with prosthetic hands -- whose realistic appearance gives way to an "eerie sensation" when one shakes a hand that feels limp, boneless, and cold.

Mori's essay made two specific predictions. First, that the relationship between human-likeness and affinity follows a non-monotonic curve with a sharp dip at near-human appearance. Second, that movement amplifies this effect: a moving curve would sit above the still curve at the peaks but plunge deeper into the valley. He speculated the effect reflected "an integral part of our instinct for self-preservation" and recommended that robot designers deliberately pursue non-human design rather than attempting to cross the valley [1].

The essay received almost no attention for three decades. Its rediscovery in the 2000s, as advances in computer graphics and robotics made humanlike artificial agents technically feasible, transformed it into one of the most widely cited concepts in human-robot interaction and animation. The authorized English translation by MacDorman and Kageki appeared in 2012, by which point the uncanny valley had generated an empirical literature numbering in the hundreds of studies -- far beyond what Mori, writing in 1970, could have anticipated [1].

What followed was five decades of research that would both validate Mori's intuition and demolish most of his specific claims.

---

## 2. The Empirical Evidence Base

### 2.1 The Systematic Review Evidence

The most comprehensive evaluation of the uncanny valley's empirical foundations comes from Katsyri et al.'s (2015) systematic review, the first to decompose Mori's theory into specific, testable sub-hypotheses and evaluate each against the empirical record [2]. After identifying approximately 550 records, deduplicating and screening to 125 assessed for eligibility, the review identified just 17 qualifying studies. The results were striking.

The "naive" uncanny valley hypothesis -- that any human-likeness manipulation will produce the characteristic non-linear dip in affinity -- received almost no support. Only 1 of 8 studies testing this hypothesis found the predicted valley [2]. The remaining 7 found no non-linear effect. In contrast, the simple monotonic relationship (more humanlike equals more likable) was supported in 7 of 9 studies, making it the most robustly supported finding in the entire review [2].

A formal meta-analysis was impossible due to heterogeneous methodologies and absent effect size statistics across the literature, a situation that has not materially improved in the decade since [2].

### 2.2 The Strongest Evidence for a Genuine Effect

Despite the systematic review's largely negative verdict, some studies provide compelling evidence that the uncanny valley is real under specific conditions.

Mathur and Reichling (2016) conducted the methodologically strongest test of the uncanny valley to date, using 80 real-world robot faces (rather than morphed images, which introduce artifacts at intermediate levels) [3]. A cubic polynomial -- a curve with two bends, matching the predicted rise-dip-recovery shape -- provided the best fit for the likability-by-human-likeness curve, explaining 29% of the variance (adjusted R-squared = 0.29, F(1) = 20.49, p < 0.001) [3]. The valley nadir occurred at a moderately human-like face (MH score +36), where likability dropped to -43 on a -100 to +100 scale.

The effect replicated with a controlled 6-face series (chi-squared(5) = 80.63, p < 0.001) and in a pre-registered replication with alternative stimuli (chi-squared(5) = 214.80, p < 0.001) [3]. This study also introduced game-theory methods to measure implicit behavioral trust, not just self-report.

Ferrey, Burleigh, and Fenske (2015) demonstrated UV-shaped affective functions using two experimental paradigms [4]. In Experiment 1 (N = 60), classic UV patterns occurred for entirely non-human animal stimuli (bistable line drawings of duck-elephant, rabbit-duck, and rhino-giraffe), with all midpoint-vs-endpoint comparisons significant (p = .006 to p < .001) [4]. In Experiment 2 (N = 69), all five 3D morph continua showed non-linear best fits, with the human-robot continuum producing a large effect (Cohen's d approximately 1.56 for midpoint vs. endpoint; values above 0.8 are conventionally considered large) [4]. Across both experiments, 72-87% of individual participants showed the UV pattern.

Diel and MacDorman (2021) tested nine competing theories simultaneously in a within-subjects design with 136 participants rating 10 stimulus conditions [5]. The overall eeriness effect was large, with experimental conditions explaining 63% of the variance in eeriness ratings (partial eta-squared = 0.63, F(9,1215) = 225.16, p < .001). Thatcherized human faces (faces with the eyes and mouth inverted, producing a subtly disturbing appearance), distorted proportions, and people with facial disfigurement all produced large increases in eeriness [5].

### 2.3 Methodological Weaknesses

The empirical literature suffers from pervasive methodological problems that make it difficult to draw firm conclusions.

**Morphing artifacts.** Image morphing -- the most common method for creating intermediate human-likeness stimuli -- introduces ghosting, double-exposure effects, and color interpolation artifacts that are most severe at intermediate morph levels, precisely where the uncanny valley is predicted [2]. In one study, participants spontaneously reported evaluating images based on "morphing noise" rather than human-likeness [2].

**Morbid outlier stimuli.** Many studies that appear to support the uncanny valley used zombies, corpses, or purposefully ill-looking characters. Katsyri et al. (2015) argue these should be treated as confounds: morbidity produces negative affect through disgust and fear pathways independent of human-likeness [2]. The morbidity hypothesis was supported in 2 of 2 studies, but this support is independent of the uncanny valley mechanism.

**Measurement incoherence.** The Japanese term *shinwakan* has been translated and operationalized inconsistently across studies -- as familiarity, pleasantness, eeriness, comfort level, likability, valence, and affinity -- without establishing equivalence [6]. No single term was used in more than half the studies in the systematic review [2]. Ho and MacDorman (2010) found that eeriness captures reactions to uncanny robots better than strangeness, suggesting the dependent variable "may not be a single phenomenon to be explained by a single theory but rather a nexus of phenomena with disparate causes" [6].

**No a priori mathematical model.** Without pre-specifying the expected curve shape, researchers are vulnerable to the Texas sharpshooter fallacy -- fitting curves to noisy data post hoc [6]. Wang et al. (2015) explicitly identify this problem: researchers have manipulated extraneous variables to map data onto an uncanny valley, creating multiple valleys of different shapes with no consistent explanation [6].

### 2.4 Replication Failures

Replication failures for the classic uncanny valley are common. Bartneck et al. (2007) found an "uncanny cliff" instead of a valley. Hanson (2005) found the valley disappeared with aesthetic enhancement. MacDorman (2006) and Poliakoff et al. (2013) failed to detect the valley entirely. Even studies using the same morphing technique produced opposing results [6]. Cheetham et al. (2014, 2015) found no stronger negative affective responses to categorically ambiguous images, and in one case found the opposite -- a "Happy Valley" [2].

### 2.5 Temporal Processing Constraints

A study demonstrating the UV effect at 50ms stimulus exposure (comparable to 3-second exposures) imposes a major constraint on theory: the effect emerges at early stages of visual processing, well within the timeframe of initial feedforward processing [7]. This rules out theories that invoke slow deliberative processes as the primary mechanism and favors configural or holistic processing accounts, which are known to operate rapidly.

The temporal dynamics study by Saygin and colleagues found that perceived animacy of android faces decreases with longer exposure time, supporting a two-stage model where an initial rapid "this looks alive" response gives way to a slower corrective "something is not right" revision [8]. Spatial frequency filtering eliminated both the animacy decline and uncanniness for android faces, suggesting the UV requires integration across coarse and fine visual processing channels [8].

---

## 3. Theoretical Explanations

At least nine theoretical accounts compete to explain the uncanny valley. The major ones can be organized along two dimensions: whether they locate the mechanism in low-level perception or higher cognition, and whether they attribute the effect to a general process or a specialized mechanism for human-like entities.

### 3.1 Perceptual Mismatch

Perceptual mismatch theory holds that the uncanny valley arises when different features of an entity send conflicting signals about its category -- for example, realistic skin paired with artificial eyes, or a human-looking face paired with a synthetic voice. This is the best-supported explanation in the empirical literature.

In Katsyri et al.'s (2015) systematic review, the inconsistency hypothesis was supported in all 4 studies that tested it, and the atypicality hypothesis in 3 of 4 [2]. Mitchell et al. (2011) demonstrated that face-voice realism incongruence significantly increased eeriness (interaction F(1,47) = 36.51, p < .001, eta-squared = 0.44) [9]. The spatial frequency study found that each frequency band (low, middle, and high) of robot and human faces was perceived as more human than the intact image, and the magnitude of this mismatch positively correlated with uncanny feelings [10]. This dose-response relationship is exactly what mismatch accounts predict.

Cross-modal evidence from Saygin et al.'s (2012) fMRI study identified the anterior intraparietal sulcus (aIPS) as a key neural locus [11]. Using repetition suppression -- a technique that detects when brain regions respond less to similar stimuli, indicating they process them as equivalent -- with android, robot, and human agents, they found the android (human appearance, mechanical motion) produced the strongest suppression in bilateral aIPS, reflecting elevated prediction error when mechanical movement violates top-down expectations of biological motion [11].

### 3.2 Configural Processing

Configural processing theory proposes that the UV effect is elicited by deviations from the configural pattern of familiar stimuli. Because humans have lifelong exposure to human faces, configural sensitivity is strongest for faces -- deviations that would be imperceptible in less familiar stimulus categories become strongly aversive.

In Diel and MacDorman's (2021) head-to-head comparison of nine theories, configural processing predicted 8 of 9 significant eeriness effects, tied for the best performance [5]. The critical evidence came from the human-likeness amplification effect: Thatcherized human faces were rated eerier than Thatcherized cats, which were eerier than Thatcherized houses (all p < .001) [5]. This amplification by human-likeness -- the same configural deviation produces stronger eeriness for more human-like stimuli -- is a signature of configural processing.

Notably, even Thatcherized houses (inanimate objects) were rated eerier than normal houses, demonstrating that the effect extends beyond anthropomorphic entities [5]. This constrains theories that would restrict the uncanny valley to human or animal stimuli.

### 3.3 The Inhibitory-Devaluation Account

Ferrey, Burleigh, and Fenske (2015) proposed that the uncanny valley is not specific to human-likeness at all, but reflects a general form of stimulus devaluation triggered by cognitive inhibition [4]. When a stimulus activates competing category representations, inhibition is recruited to resolve the conflict, and this inhibition produces negative affect as a byproduct.

This account makes two predictions that compete with pathogen-avoidance theories. First, UV effects should occur for non-human stimuli. Second, the affective minimum should occur at the continuum midpoint (maximal category conflict), not near the human end. Both predictions were confirmed: UV-shaped affective functions occurred for bistable animal drawings with zero human features, and the valley nadir consistently appeared at the midpoint across all continua tested [4].

The authors connect the uncanny valley to established conflict-affect phenomena including cognitive dissonance, Stroop interference, and the broader inhibitory-devaluation literature, positioning the UV as "a specific instance of a more general form of stimulus devaluation" [4].

### 3.4 The Bayesian Model

Moore (2012) offered an early quantitative mathematical model of the uncanny valley, extending Feldman et al.'s perceptual magnet effect to multiple dimensions [12]. The model decomposes Mori's vertical axis into two components: familiarity (probability of stimulus occurrence) minus perceptual tension (variance of displacement functions across perceptual dimensions). The affinity function F[S] = p(S) - k * V[S] produces the valley dip when perceptual tension exceeds familiarity [12].

This model makes several important contributions. It resolves the longstanding confusion between "familiarity" and "affinity" in Mori's *shinwakan*. It predicts individual differences through the observer-sensitivity parameter k. And it predicts that even small anomalies in a single perceptual cue can trigger strong uncanny responses when the rest of the stimulus strongly cues "human" [12]. Notably, the model also predicts that movement should amplify the uncanny valley effect, a prediction that has been empirically falsified (see Section 4.4). However, the model presents theoretical predictions and simulations without new experimental data, and its Gaussian distribution assumptions remain unvalidated.

### 3.5 Mind Perception

Gray and Wegner (2012) proposed a social-cognitive account locating the uncanny valley in theory-of-mind reasoning rather than low-level perception [13]. Across three experiments, they demonstrated that the attribution of experience (capacity to feel and sense) -- not agency (capacity to plan and act) -- drives uncanniness. A machine described as capable of experience was rated more unnerving even without humanlike appearance, and humans described as lacking experience ("philosophical zombies") were also eerie [13]. This symmetry suggests experience is perceived as fundamental to humanness, and violations in either direction produce uncanniness.

Stein and Ohler (2017) extended this with their "uncanny valley of mind" concept: in a VR study (N = 92), participants experienced significantly stronger eeriness when they believed empathic digital characters were autonomous AI, with no differences in human-likeness or attractiveness ratings [14]. The eeriness arose from the attribution of autonomous mental states to a non-human entity, independent of appearance.

### 3.6 Frequency-Based Sensitization

Burleigh and Schoenherr (2015) proposed that affective responses in the uncanny valley are governed by exemplar frequency information stored in long-term memory, independently of categorical perception [15]. Using a category-learning paradigm with non-human creature morphs, they demonstrated that manipulating exemplar frequency altered eeriness patterns without shifting the category boundary. Only asymmetric frequency distributions (one category with fewer high-frequency exemplars, approximating extensive experience with humans) produced the full classic UV pattern [15].

This finding challenges pure categorical perception accounts because correlations between categorization accuracy and eeriness were non-significant across all conditions (all p > 0.5), and correlations between response time and eeriness were also non-significant (all p > 0.3) [15].

### 3.7 Threat and Pathogen Avoidance

Evolutionary accounts propose the uncanny valley serves an innate mechanism for avoiding danger -- specifically, conspecifics who appear diseased or deformed. Indirect support comes from MacDorman and Entezari (2015) showing that disgust sensitivity, animal reminder sensitivity, neuroticism, and anxiety predict UV sensitivity [6]. Threat avoidance predicted 7 of 9 significant effects in Diel and MacDorman (2021) [5].

However, pathogen-avoidance accounts are directly challenged by evidence that UV effects occur for entirely non-human stimuli. Ferrey et al. (2015) demonstrated UV-shaped functions using duck-elephant, rabbit-duck, and rhino-giraffe morphs with zero human features [4]. If the UV is an evolved mechanism for detecting diseased conspecifics, it should not operate on non-conspecific stimuli.

### 3.8 The Dehumanization Hypothesis

Wang, Lilienfeld, and Rochat (2015) proposed a two-step cognitive process: anthropomorphism followed by dehumanization [6]. The uncanny feeling arises not from attributing humanness to a replica, but from subsequently perceiving the anthropomorphized entity as lacking human nature (emotions, warmth). This draws on Haslam's dual model of dehumanization and is supported by Looser et al.'s (2013) two-stage face processing model, where Stage 1 (inferior occipital gyrus) facilitates anthropomorphism and Stage 2 (lateral fusiform gyrus, STS) scrutinizes for animacy [6].

The temporal dynamics study provides support: android faces showed decreasing perceived animacy with longer exposure, consistent with dehumanization rather than mind perception [8].

### 3.9 Category Uncertainty: The Weakest Account

Despite its popularity, the categorization-ambiguity account has the weakest empirical support. In Katsyri et al.'s (2015) review, categorization ambiguity did not reliably predict negative affinity (0 of 2 studies for H3c) [2]. Burleigh and Schoenherr (2015) found categorization accuracy and eeriness ratings were uncorrelated [15]. The 50ms exposure study found the eeriest faces were not the hardest to categorize [7]. The prosthetic hands study found a double dissociation: the eeriest category (H- prosthetics) was not the most categorically ambiguous (H+ prosthetics were slower to classify but less eerie) [16]. Mathur and Reichling (2016) found rating time mediated only a non-significant 3% of the likability effect [3]. In Diel and MacDorman's (2021) direct comparison, category uncertainty predicted only 3 of 9 significant effects -- the worst performance of any theory [5].

---

## 4. The Central Disputes

### 4.1 Is Categorization Ambiguity Causal?

The most consequential debate in the field is whether categorical uncertainty causes the uncanny valley. Multiple converging dissociations now challenge this account. The 50ms exposure study showed eeriness peaks and categorization difficulty peaks did not coincide [7]. The prosthetic hands study showed H- prosthetics (less human-like) were eeriest while H+ prosthetics (more human-like, closer to the category boundary) were slowest to classify [16]. Mathur and Reichling found rating time accounted for only 3% of the human-likeness to likability relationship [3]. These converging results strongly suggest categorical uncertainty co-occurs with the UV but does not cause it.

The debate between Ferrey, Burleigh, and Fenske (categorization-based stranger avoidance) and MacDorman and Chattopadhyay (realism inconsistency) remains unresolved, highlighting a fundamental methodological challenge: categorization difficulty and realism inconsistency are highly correlated in most stimulus sets, making clean dissociation extremely difficult [17].

### 4.2 Adding Mind vs. Subtracting Mind

Two social-cognitive accounts make competing predictions about the temporal dynamics of mind attribution. Gray and Wegner's (2012) mind perception hypothesis predicts that uncanny androids should be rated high in perceived animacy at longer exposure, as perceivers attribute more mind [13]. Wang et al.'s (2015) dehumanization hypothesis predicts that uncanny androids should be rated high in animacy at brief exposure (initial anthropomorphism) but low in animacy at longer exposure (subsequent dehumanization) [6].

The temporal dynamics evidence currently favors dehumanization: android faces showed decreasing perceived animacy with longer viewing [8]. However, the 50ms exposure study showed the UV effect already present at very brief durations, meaning the perceptual signature of uncanniness is established rapidly, before the proposed two-step process has time to unfold fully [7]. This tension remains unresolved.

### 4.3 Evolutionary Specialization vs. General Process

A fundamental divide separates accounts that view the uncanny valley as an evolved, specialized mechanism (pathogen avoidance, mate selection, stranger avoidance) from those that view it as an instance of general cognitive processes (inhibitory devaluation, configural processing, perceptual mismatch).

The strongest evidence against specialization is the non-human stimulus finding. UV-shaped affective functions occur for duck-elephant morphs, rabbit-duck bistable images, and non-human creature continua [4][15]. These stimuli have no human features whatsoever, yet produce the same non-linear pattern. This directly contradicts accounts that restrict the UV to conspecific stimuli and favors accounts that treat it as a general consequence of category conflict or configural deviation.

### 4.4 Does Movement Amplify the Effect?

Mori's prediction that movement amplifies the uncanny valley received no empirical support. Thompson et al. (2011) parametrically manipulated three kinematic features of walking avatars and found monotonic (not valley-shaped) relationships between movement human-likeness and ratings of humanness, familiarity, and eeriness [18]. Piwek et al. (2014) independently replicated this finding [2]. Both studies in Katsyri et al.'s (2015) review that tested movement effects found linear rather than non-linear relationships [2]. This contradicts a central pillar of Mori's original hypothesis and suggests the uncanny valley may be specific to static appearance.

### 4.5 Innate or Acquired?

The evidence weighs against an innate mechanism. A study of 240 participants aged 3-18 found the UV effect does not appear until approximately age 9, with younger children showing no difference in creepiness between human-like and machine-like robots [19]. The emergence around age 9 coincides with developmental shifts in theory of mind, category reasoning, and understanding of artifact vs. biological distinctions. This argues against evolutionary-essentialist accounts that predict the UV should be present from birth or early infancy.

Cross-species evidence adds nuance: macaque monkeys show differential attention to realistic vs. unrealistic synchronized monkey faces, and 12-month-old infants look longer at faces combined with uncanny features [6]. This creates a tension: some sensitivity to uncanny-like features appears early, yet the full affective response does not emerge until middle childhood, suggesting perceptual sensitivity may precede affective discomfort.

---

## 5. Individual and Cultural Variation

### 5.1 Personality and Dispositional Traits

Individual differences in uncanny valley sensitivity are predicted by personality and dispositional traits. MacDorman and Entezari (2015) found that disgust sensitivity, animal reminder sensitivity, neuroticism, anxiety, and religious fundamentalism all predict UV sensitivity (as reviewed by Wang et al., 2015 [6]). Moore's (2012) Bayesian model formalizes these differences through a weighting parameter k (observer sensitivity to perceptual conflict), where small k means insensitivity to cue conflicts and large k indicates strong sensitivity [12].

Empirically, 13-28% of participants in Ferrey et al. (2015) did not show the UV pattern across stimulus continua, suggesting meaningful individual differences in susceptibility [4]. These individual differences remain underexplored and poorly understood.

### 5.2 Experience-Based Modulation

Upper-limb and lower-limb amputees (N = 19 total) show significantly reduced eeriness responses to prosthetic hands compared to non-amputee controls, prosthetists, and simulator-trained controls [20]. This small sample limits statistical power and generalizability, though the effect was consistent across both upper- and lower-limb groups. Critically, this reduction occurred without any change in perceived human-likeness: amputees found prosthetics equally human-like but less eerie. Neither prolonged visual exposure (prosthetists) nor brief motor training (simulator group) reproduced the effect, pointing to prolonged embodied experience as the critical factor in attenuating the UV response [20].

This demonstrates that the uncanny valley is modifiable through lived experience rather than being a fixed perceptual response. It supports frequency-based and experiential accounts over hardwired evolutionary mechanisms.

### 5.3 Developmental Trajectory

The developmental study of 240 children and adolescents established that the UV effect does not emerge until approximately age 9 [19]. However, the study used only two robot stimuli (one machine-like, one human-like), which limits the granularity of conclusions about the shape of the developmental trajectory. Children's uncanny valley feelings are linked to mind perception: those who attributed more human-like mental states to human-like robots experienced stronger creepiness. This suggests the UV response depends on cognitive development of theory of mind and category reasoning about living vs. non-living entities, rather than on innate perceptual mechanisms [19].

### 5.4 Empathy: A Non-Predictor

In Diel and MacDorman (2021), the 40-item Empathy Quotient was a non-significant negative predictor of eeriness (r = -0.07, p = .055) [5]. Rather than more empathic individuals finding uncanny entities eerier, the direction was reversed. This contradicts the prediction that the UV should be stronger in individuals with greater empathic abilities and challenges empathy-based theories that attribute uncanniness to feeling empathy for an entity known to be inanimate.

### 5.5 Cultural Coverage: A Major Gap

Cross-cultural coverage in the uncanny valley literature is thin. Most studies use WEIRD (Western, Educated, Industrialized, Rich, Democratic) populations. The frequency-based sensitization model predicts that populations with different exposure histories to human-like entities -- such as cultures with greater familiarity with humanoid robots -- should show different UV profiles [15]. However, direct cross-cultural comparisons remain scarce, and the field lacks the systematic cross-cultural data needed to evaluate whether the uncanny valley is a human universal or culturally shaped.

---

## 6. Arguments Against the Uncanny Valley

### 6.1 The Empirical Record Is Weak

The most comprehensive evaluation of the uncanny valley hypothesis found that the naive prediction (any human-likeness manipulation produces the valley) was supported in only 1 of 8 studies [2]. Wang, Lilienfeld, and Rochat (2015) concluded that the existence of the uncanny valley as a genuine phenomenon remains an open question [6]. Several studies failed to detect the predicted valley shape, and even studies using the same morphing technique produced opposing results.

### 6.2 Stimulus Confounds

Image morphing artifacts systematically confound uncanny valley research. Ghosting, double-exposure effects, and blurring from color interpolation are most severe at intermediate morph levels -- exactly where the UV is predicted [2]. Studies that appeared to support the UV often used zombies, corpses, or purposefully ill-looking characters, confounding human-likeness with morbidity [2]. The Katsyri et al. review excluded several seminal studies for lacking statistical tests or being confounded by morphing artifacts and heterogeneous stimuli.

### 6.3 The Texas Sharpshooter Fallacy

Without an a priori mathematical model of the UV's expected shape, researchers are vulnerable to fitting curves to noisy data post hoc. Wang et al. (2015) identified this as a fundamental problem: researchers have manipulated extraneous variables to map data onto an uncanny valley, creating multiple valleys of different shapes with no consistent explanation [6]. The absence of pre-specified curve shapes allows confirmation bias to influence interpretation.

### 6.4 The Dependent Variable Problem

*Shinwakan* has been translated inconsistently across studies -- as familiarity, pleasantness, eeriness, comfort level, likability, valence, and affinity -- without establishing equivalence [6]. Single-item measures lack reliability, and likability itself may not be unidimensional. This measurement incoherence means findings across studies may not be comparable.

### 6.5 Not Innate, Not Universal

The UV effect does not appear until age 9, arguing against innate mechanisms [19]. Movement does not produce the predicted valley [18]. The effect occurs for entirely non-human stimuli, undermining conspecific-specific accounts [4]. Amputees show reduced eeriness, demonstrating the response is experience-modifiable [20]. These findings collectively challenge the notion of the uncanny valley as a fixed, universal, evolved phenomenon.

### 6.6 The Uncanny Phenomenon vs. the Uncanny Valley Hypothesis

Wang et al. (2015) draw a crucial distinction: the uncanny *phenomenon* (people find near-human entities unsettling) is a psychological question with clear evidence, while the uncanny *valley hypothesis* (this unease follows a specific non-monotonic curve as a function of human-likeness) is an engineering claim with far weaker support [6]. "The existence of an uncanny reaction does not validate the valley model."

---

## 7. The Shape of the Function

### 7.1 The Cubic Valley

The strongest evidence for the shape of the uncanny valley function comes from Mathur and Reichling (2016). A third-degree polynomial provided the best and most parsimonious fit for the likability-by-human-likeness curve using 80 real-world robot faces [3]. The curve showed an initial rise to an apex at MH score -66, a sharp decline to a nadir of -43 at MH score +36 (somewhat human-like), and a recovery to +43 at fully human. This cubic shape outperformed both linear and quadratic models (F(1) = 20.49, p < 0.001) [3].

### 7.2 Non-Linear Models Decisively Outperform Linear

Ferrey et al. (2015) found that linear models were decisively rejected across all continua tested (Akaike Weights -- a measure of how well each model fits relative to alternatives -- 0.00-0.02 vs. 0.28-0.93 for best-fitting non-linear models) [4]. The affective minimum consistently occurred at the continuum midpoint -- the point of maximal category conflict -- not shifted toward the human end as pathogen-avoidance accounts predict.

### 7.3 Higher-Order Functions

The shape depends on the stimulus and exposure conditions. Burleigh and Schoenherr (2015) found that the eeriness function required higher-order polynomials (quartic or quintic) rather than the simple quadratic predicted by category boundary models [15]. Only the asymmetric frequency condition (UFUD) produced the classic Mori UV with a slope and skewed valley. This demonstrates that the shape of the UV function depends critically on the frequency distribution of exemplars experienced by the observer.

### 7.4 The Trust Valley Is Fragile

While the likability UV is robust, the trust UV is more fragile. In Mathur and Reichling's data, the trust UV disappeared when the most human-like 25% of faces were excluded (F(3) = 1.57, p = 0.20) and failed to replicate with male stimuli (chi-squared(5) = 8.76, p = 0.12) [3]. This indicates the UV's behavioral consequences may be more context-dependent than explicit likability ratings suggest.

### 7.5 Movement Produces Monotonic Functions

For movement, the relationship is not valley-shaped but monotonic. Thompson et al. (2011) parametrically manipulated walking avatar kinematics and found all rating dimensions (humanness, familiarity, eeriness) changed monotonically with human-likeness [18]. This directly contradicts Mori's prediction of a deeper valley for moving entities.

---

## 8. The Evolution of Understanding

### 8.1 From Personal Observation to Systematic Science (1970-2015)

Mori's 1970 essay was a personal observation, not an experimentally verified finding [1]. For decades, the uncanny valley was treated as folk wisdom rather than a testable hypothesis. The first systematic review (Katsyri et al., 2015) marked a turning point, decomposing Mori's informal proposal into 13 testable sub-hypotheses and evaluating each against the empirical record [2]. The result was transformative: the naive uncanny valley was nearly unsupported, but specific conditions (perceptual mismatch, atypicality) were well-supported.

### 8.2 The Computational Turn (2012)

Moore's (2012) Bayesian model provided an early quantitative mathematical explanation of the uncanny valley, moving beyond qualitative accounts to computationally explicit, testable predictions [12]. The model resolved the confusion between familiarity and affinity in Mori's original formulation and connected the UV to established literature on categorical perception and the perceptual magnet effect.

### 8.3 Neuroimaging Evidence (2012)

Saygin et al. (2012) provided the first direct neuroimaging evidence for the uncanny valley, identifying the anterior intraparietal sulcus as a key neural locus and establishing predictive coding as a mechanistic framework [11]. This moved the field beyond purely behavioral measures to identifiable neural correlates in the action perception system.

### 8.4 The Social-Cognitive Expansion (2012-2017)

Gray and Wegner (2012) shifted uncanny valley research from perceptual similarity to categorical violations in mental state reasoning, introducing the mind perception hypothesis [13]. Wang et al. (2015) countered with the dehumanization hypothesis, proposing a two-step process of anthropomorphism followed by dehumanization [6]. Stein and Ohler (2017) extended the concept beyond appearance to the "uncanny valley of mind," demonstrating that eeriness arises from mental-state attribution independent of visual design [14]. This social-cognitive expansion broadened the uncanny valley from a question about how things look to a question about how we reason about what things are.

### 8.5 The Non-Human Stimulus Challenge (2015)

Ferrey, Burleigh, and Fenske's (2015) demonstration that UV-shaped affective functions occur for entirely non-human animal stimuli challenged the dominant framing of the uncanny valley as tied to human-likeness [4]. This positioned the UV as a specific instance of a general cognitive phenomenon rather than a specialized mechanism for near-human entities.

### 8.6 Direct Theory Comparison (2021)

Diel and MacDorman's (2021) study was the first to test nine competing theories simultaneously in a single experiment with the same participants, stimuli, and scales [5]. This methodological advance enabled direct comparison of predictive power, revealing configural processing and atypicality+ as the strongest performers and category uncertainty as the weakest.

### 8.7 Temporal Processing Constraints (2024)

The 50ms exposure study established that the UV effect arises at very early stages of visual processing, ruling out slow deliberative mechanisms and favoring configural or holistic accounts [7]. Combined with the temporal dynamics evidence showing animacy decreases with longer exposure [8], this work has begun to constrain theories by the speed at which their proposed mechanisms can operate.

---

## 9. Synthesis and Open Questions

### 9.1 What the Evidence Establishes

After five decades, the evidence establishes several points with reasonable confidence:

1. **The uncanny valley is real under specific conditions.** When perceptual features send conflicting signals about an entity's category, a non-linear dip in affinity occurs. This is supported by multiple independent paradigms and effect sizes range from medium to very large.

2. **It is not a universal consequence of human-likeness.** The naive prediction that any human-likeness manipulation produces the valley is overwhelmingly rejected. The effect appears only under specific conditions, primarily perceptual mismatch and configural deviation.

3. **Configural processing and perceptual mismatch are the best-supported mechanisms.** These accounts predict the most effects in direct comparisons and are supported by converging behavioral, neuroimaging, and temporal-processing evidence.

4. **Categorization ambiguity is not the causal mechanism.** Multiple dissociations between categorization difficulty and eeriness now challenge this popular account.

5. **The effect is experience-dependent and not innate.** It does not appear until age 9 and is attenuated by embodied experience, arguing against purely evolutionary accounts.

These conclusions should be interpreted with the caveat that the core evidence base is drawn almost entirely from US/Canadian MTurk and undergraduate samples (WEIRD populations), and generalizability to other cultures remains uncertain.

### 9.2 The Unresolved Tensions

Several fundamental questions remain open:

1. **General vs. specialized mechanism.** Does the uncanny valley reflect a general cognitive process (inhibitory devaluation, configural processing) that happens to be amplified for human stimuli, or is there a specialized mechanism for near-human entities?

2. **Mind perception vs. dehumanization.** Does uncanniness involve adding too much mind to a machine or subtracting mind from something that looks human? The temporal evidence currently favors dehumanization, but the 50ms onset of the UV effect suggests the perceptual signature is established before social-cognitive processes have time to fully engage.

3. **Single mechanism vs. multiple mechanisms.** Ho and MacDorman's (2010) suggestion that the uncanny valley "may not be a single phenomenon to be explained by a single theory but rather a nexus of phenomena with disparate causes" may be correct. Different mechanisms may operate at different levels (neural, perceptual, cognitive, evolutionary) and different timescales.

4. **Cross-cultural variation.** The field lacks systematic cross-cultural data to evaluate whether the uncanny valley is a human universal or culturally shaped by exposure to humanoid entities.

### 9.3 What Would Resolve the Debate

Progress requires several methodological advances: pre-registration of expected curve shapes to avoid the Texas sharpshooter fallacy, standardized dependent variables with established psychometric properties, stimuli that dissociate categorization difficulty from perceptual mismatch, cross-cultural and developmental studies with non-WEIRD populations, and longitudinal work tracking how the UV response changes with exposure to humanoid agents.

---

## Methodology

This report synthesizes findings from a deep research session on the uncanny valley as a psychological phenomenon. The research process involved:

- **Deep reads:** 21 sources read in full with structured note-taking
- **Abstract-only sources consulted:** 143 (used for context but not cited as primary evidence)
- **Web sources:** 87
- **Total searches:** 38 (29 discovery, 9 recovery)
- **Total sources tracked:** 389 (133 excluded as irrelevant)
- **Downloaded with content:** 113
- **Quality issues:** 6 mismatched content files, 12 degraded PDFs

All cited sources (References section) were read in full and validated by the reader agent. Sources known only from abstracts are listed separately in Further Reading.

**Limitations of this review.** The deep-read sources are weighted toward English-language publications, and the literature search was constrained by API availability. Cross-cultural evidence is particularly thin, with most studies conducted on WEIRD populations. Many published studies in this field use small samples, single-item measures, and stimuli with known confounds. The report flags these limitations throughout rather than obscuring them behind hedging language.

---

## References

[1] Mori, M. (1970/2012). The uncanny valley. *Energy*, 7(4), 33-35. (Translated by K. F. MacDorman & N. Kageki, *IEEE Robotics & Automation Magazine*, 98-100.)

[2] Katsyri, J., Forger, K., Makarainen, M., & Takala, T. (2015). A review of empirical evidence on different uncanny valley hypotheses: Support for perceptual mismatch as one road to the valley of eeriness. *Frontiers in Psychology*, 6, 390.

[3] Mathur, M. B., & Reichling, D. B. (2016). Navigating a social world with robot partners: A quantitative cartography of the Uncanny Valley. *Cognition*, 146, 22-32.

[4] Ferrey, A. E., Burleigh, T. J., & Fenske, M. J. (2015). Stimulus-category competition, inhibition, and affective devaluation: A novel account of the uncanny valley. *Frontiers in Psychology*, 6, 249.

[5] Diel, A., & MacDorman, K. F. (2021). Creepy cats and strange high houses: Support for configural processing in testing predictions of nine uncanny valley theories. *Journal of Vision*, 21(4), 1.

[6] Wang, S., Lilienfeld, S. O., & Rochat, P. (2015). The uncanny valley: Existence and explanations. *Review of General Psychology*, 19(4), 393-407.

[7] Yam, J., Gong, T., & Xu, H. (2024). A stimulus exposure of 50 ms elicits the uncanny valley effect. *Heliyon*, 10(6), e27977.

[8] Wang, S., Cheong, Y. F., Dilks, D. D., & Rochat, P. (2020). The uncanny valley phenomenon and the temporal dynamics of face animacy perception. *Perception*, 49(10), 1069-1089.

[9] Mitchell, W. J., Szerszen, K. A., Sr., Lu, A. S., Schermerhorn, P. W., Scheutz, M., & MacDorman, K. F. (2011). A mismatch in the human realism of face and voice produces an uncanny valley. *i-Perception*, 2(1), 10-12.

[10] Ito, M., & Suzuki, A. (2024). Discrepancies in perceived humanness between spatially filtered and unfiltered faces and their associations with uncanny feelings. *Perception*, 53(8), 529-543.

[11] Saygin, A. P., Chaminade, T., Ishiguro, H., Driver, J., & Frith, C. (2012). The thing that should not be: Predictive coding and the uncanny valley in perceiving human and humanoid robot actions. *Cerebral Cortex*, 22(7), 1596-1605.

[12] Moore, R. K. (2012). A Bayesian explanation of the "Uncanny Valley" effect and related psychological phenomena. *Scientific Reports*, 2, 864.

[13] Gray, H. M., & Wegner, D. M. (2012). Feeling robots and human zombies: Mind perception and the uncanny valley. *Cognition*, 125(1), 125-128.

[14] Stein, J.-P., & Ohler, P. (2017). Venturing into the uncanny valley of mind -- The influence of mind attribution on the acceptance of human-like characters in a virtual reality setting. *Computers in Human Behavior*, 74, 331-347.

[15] Burleigh, T. J., & Schoenherr, J. R. (2015). A reappraisal of the uncanny valley: Categorical perception or frequency-based sensitization? *Frontiers in Psychology*, 5, 1488.

[16] Poliakoff, E., O'Kane, S., Carefoot, O., Kyberd, P., & Gowen, E. (2018). Investigating the uncanny valley for prosthetic hands. *Prosthetics and Orthotics International*, 42(1), 21-27.

[17] Ferrey, A. E., Burleigh, T. J., & Fenske, M. J. (2015). When categorization-based stranger avoidance explains the uncanny valley: A comment on MacDorman and Chattopadhyay (2016). *Cognition*, 153, 136-139.

[18] Thompson, J. C., Trafton, J. G., & McKnight, P. (2011). The perception of humanness from the movements of synthetic agents. *Perception*, 40(6), 695.

[19] Brink, K. A., Gray, K., & Wellman, H. M. (2019). Creepiness creeps in: Uncanny valley feelings are acquired in childhood. *Child Development*, 90(4), 1202-1214.

[20] Buckingham, G., Parr, J., Wood, G., Day, S., Chadwell, A., Head, J., Galpin, A., Kenney, L., Kyberd, P., Gowen, E., & Poliakoff, E. (2019). Upper- and lower-limb amputees show reduced levels of eeriness for images of prosthetic hands. *Psychonomic Bulletin & Review*, 26(4), 1295-1302.

---

## Further Reading

The following sources were consulted as abstracts only and are included for completeness. They should not be treated as reader-validated evidence.

- MacDorman, K. F., & Chattopadhyay, D. (2016). Reducing consistency in human realism increases the uncanny valley effect; increasing category uncertainty does not. *Cognition*. (Abstract only. Reported N=548 across three experiments, finding realism inconsistency produces the UV effect but category uncertainty does not.)

- A meta-analysis of the uncanny valley's independent and dependent variables. (Abstract only. 72 studies out of 468 screened. Found no consensus on theoretical basis or methodologies, highlighting field fragmentation.)

- Human perception of animacy in light of the uncanny valley phenomenon. *PubMed*. (Abstract only. N=160 across three studies using 89 face stimuli. Study 3 found categorical uncertainty correlated with negative emotions.)
