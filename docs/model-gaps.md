# Model gaps

What the model leaves out, and how each gap limits the findings. A finding is only as good as the rules behind it, so every query result should be read against this list. Entries are removed when a milestone closes them. The roadmap that may close them is under [Milestones](v2-brief.md#milestones) in the brief.

Started 29 October 2026. Legal sources were checked on that date on legislation.gov.uk.

Each entry gives the gap, its source, its effect on findings, and where it might be fixed.

## Rules that cross assessment periods

### Surplus earnings, and an award ending after a nil period

- **Gap.** The rules compute one assessment period at a time. When earnings reduce an award to nil, the award can end, and a new claim within 6 months counts earnings above "the nil UC threshold plus £300" as surplus earnings ([regulation 54A](https://www.legislation.gov.uk/uksi/2013/376/regulation/54A) of the Universal Credit Regulations 2013). Neither the end of the award nor surplus earnings is modelled. [Regulation 32A](https://www.legislation.gov.uk/uksi/2013/380/regulation/32A) of the Universal Credit etc. (Claims and Payments) Regulations 2013 deals with an award that "ceases because that condition is not met" (the financial condition), and lets the claimant be treated as claiming again in each of up to 5 following months. The project reads this as: an assessment period with a nil award, because of earnings, ends the award. That reading is for specialist review.
- **Effect.** Moving pay between periods gains nothing beyond rounding while the award stays above nil in every period, because the award is a concave function of earnings. All the larger gains come from pushing one period to nil, which is where regulation 54A applies. Queries about timing are therefore limited to splits where every period's award stays above nil. Gains from nil periods are not reported.
- **Where.** The milestone that adds rules crossing periods. Note that the nil UC threshold divides by 55% (20/11), which reaches the translator's gap for decimal rates with no terminating decimal form.

## Rounding

- **Gap.** The stage at which regulation 6 rounds is an open question with three readings. The rules follow one of them.
- **Effect.** Awards can differ by a penny between readings, and findings measured in pennies (rounding gains, for example) depend on the reading.
- **Where.** See the [mismatch log](mismatches.md), entry 1, and the rounding-stage candidate in the brief.

## Household and claim

- **Single claimant only.** No couples or joint claims, so the couple finding cannot be a judgement point yet.
- **No children.** No child element, and responsibility for a child does not open the work allowance.
- **Other elements.** Only the standard allowance and the housing costs element are modelled. The LCWRA, carer and childcare elements are not. The LCW element kept under transitional provisions from before 3 April 2017 is not.
- **Unearned income and capital.** Unearned income is zero, and capital is assumed to be below the limit.
- **Earnings.** `earned_income` is earned income as regulation 55 defines it, net of income tax, National Insurance and pension contributions. Gross pay, tax and National Insurance are not modelled, so findings cannot speak about gross pay or net household income.
- **Self-employment.** No self-employed earnings and no minimum income floor, so the "gainful self-employment" finding cannot be a judgement point yet.
- **Benefit cap.** Not modelled, nor its earnings exemption.

## Housing

- **Gap.** The housing costs element is one input, taken as already worked out. Rent, service charges, the Local Housing Allowance cap, the under-occupancy deduction, housing cost contributions from non-dependants, converting weekly rent to monthly, and owner-occupiers are not modelled.
- **Reading.** Regulation 22(2) applies the lower work allowance when the award "does contain an amount for the housing costs element". The rules read that as an element above zero, as PolicyEngine UK does.
- **Effect.** Findings hold for a given element, not for a given rent.

## Judgement points

- **Gap.** A judgement point is a Boolean or a small enumeration with no probability attached. Only limited capability for work is modelled as one.
- **Effect.** A query can say what a finding is worth, not how likely it is.

## Outside the model

- **No specialist review.** No welfare rights adviser or social security policy specialist has reviewed the rules or the readings of the regulations. Each reading is the project's own, recorded with its sources. Findings carry this caveat until such a review takes place.
- **DWP's own calculation software** cannot be tested from outside. The model follows the regulation text. Where practice differs, the model will not show it.
- **Decision makers' practice and guidance,** including *Advice for Decision Making*, are not modelled. Only the outcome of a finding is an input.
