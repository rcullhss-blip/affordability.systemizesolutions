"""
Lender-type classifier and CONC reference selector.
"""

LENDER_TYPE_MAP: dict[str, str] = {}

_PAYDAY = [
    "sunny", "quickquid", "wonga", "ferratum", "mr lender", "peachy",
    "pounds to pocket", "wageday advance", "uncle buck", "drafty", "bamboo",
    "lending stream", "safetynet credit", "everyday loans", "cash4unow",
    "myjar", "wizzcash", "cashfloat", "piggybank", "satsuma", "cash converters",
    "dollar financial", "speedycash", "toothfairy", "juo loans",
]
_CREDIT_CARD = [
    "aqua", "vanquis", "capital one", "marbles", "fluid", "newday", "barclaycard",
    "tesco bank", "argos card", "opus", "jaja", "zable", "halifax credit",
    "lloyds bank credit", "natwest card", "barclays bank", "santander credit",
    "hsbc", "mbna", "118118 cards", "zopa credit", "virgin money",
    "creation consumer", "creation financial", "ikano", "onmo", "zempler",
    "oakbrook", "bits credit", "fluid mastercard", "link financial",
]
_CATALOGUE = [
    "very", "littlewoods", "jd williams", "studio", "jacamo", "freemans",
    "next directory", "next retail", "simply be", "fashion world", "marisota",
    "ambrose wilson", "premier man", "home essentials", "crazy clearance",
    "damart", "afibel", "shop direct",
]
_MOTOR_FINANCE = [
    "moneybarn", "motonovo", "black horse", "secure trust bank motor",
    "close motor finance", "paragon motor finance", "alphera financial",
    "rci financial", "fca automotive", "stellantis financial",
    "mercedes benz financial", "mercedes benz fnancial",
    "honda finance europe", "bmw financial services",
    "toyota financial services", "volkswagen financial",
    "fce bank", "oodle", "autolend", "lombard asset finance",
    "car finance 247", "247 money", "mallard vehicle", "specialist motor finance",
    "mi vehicle finance", "conister bank", "equifinance",
    "koyo finance", "first senior finance",
]
_OVERDRAFT = [
    "barclays bank", "lloyds bank", "halifax bank", "santander bank",
    "natwest bank", "hsbc bank", "tsb", "co-op bank", "cooperative bank",
    "monzo", "starling",
]
_PERSONAL_LOAN = [
    "amigo", "provident", "morses club", "likely loans", "118118 money",
    "avant credit", "hitachi", "tesco personal finance",
    "sainsbury", "m&s bank", "post office", "lendable", "zopa ltd",
    "shawbrook", "bamboo loans", "tandem bank", "oakbrook finance",
    "premium credit", "snap finance", "loans 2 go", "uk credit",
    "fair finance", "live lend", "abound", "admiral financial",
    "propensio", "plata finance", "wollit", "steadypay",
]
_HOME_CREDIT = [
    "provident financial", "morses", "mutual", "naylors", "moneyline",
    "five lamps", "abcul", "scotwest credit union", "bristol credit union",
    "enterprise credit union", "hampshire credit union",
]
_GUARANTOR = [
    "amigo loans", "guarantor my loan", "uk credit", "buddy loans",
    "george banco", "1plus1",
]

# Entities that may be brokers/intermediaries rather than regulated creditors.
# Presence of these entities as a "lender" on a credit report warrants solicitor verification
# before a LOC is issued, as the actual regulated creditor may be a different entity.
_POSSIBLE_INTERMEDIARY = {
    "car finance 247",   # Primarily a credit broker / comparison platform
    "zuto",              # Motor finance broker
    "autolend",          # Motor finance broker
    "247 money group",
}


def _register(lenders: list[str], lender_type: str):
    for name in lenders:
        LENDER_TYPE_MAP[name.lower()] = lender_type


_register(_PAYDAY,        "payday")
_register(_CREDIT_CARD,   "credit_card")
_register(_CATALOGUE,     "catalogue")
_register(_MOTOR_FINANCE, "motor_finance")
_register(_OVERDRAFT,     "overdraft")
_register(_PERSONAL_LOAN, "personal_loan")
_register(_HOME_CREDIT,   "home_credit")
_register(_GUARANTOR,     "guarantor")


def classify_lender(lender_name: str) -> str:
    name_lower = lender_name.lower().strip()
    for key, ltype in LENDER_TYPE_MAP.items():
        if key in name_lower or name_lower in key:
            return ltype
    return "other"


def is_possible_intermediary(lender_name: str) -> bool:
    """Return True if this entity may be a broker/intermediary rather than a regulated creditor."""
    name_lower = lender_name.lower().strip()
    return any(b in name_lower for b in _POSSIBLE_INTERMEDIARY)


CONC_REFERENCES: dict[str, str] = {
    "payday":        "FCA CONC 5.2A — Creditworthiness Assessment (High-Cost Short-Term Credit)",
    "credit_card":   "FCA CONC 5.2 — Creditworthiness Assessment; CONC 6.2 — Persistent Debt",
    "catalogue":     "FCA CONC 5.2 — Creditworthiness Assessment; CONC 5.3 — Proportionate Checks",
    "motor_finance": "FCA CONC 5.2A — Creditworthiness Assessment; CONC 5.2A.12R — Sustainable Repayment",
    "overdraft":     "FCA CONC 5.2 — Creditworthiness Assessment; FCA Overdraft Pricing Rules 2020",
    "personal_loan": "FCA CONC 5.2 — Creditworthiness Assessment; CONC 5.2.1R",
    "guarantor":     "FCA CONC 5.2 — Creditworthiness Assessment (Borrower and Guarantor)",
    "home_credit":   "FCA CONC 5.2A — High-Cost Credit Affordability; CONC 5.5 — Irresponsible Lending",
    "other":         "FCA CONC 5.2 — Creditworthiness Assessment; CONC 5.3 — Affordability",
}

CONC_SPECIFIC_RULES: dict[str, list] = {
    "payday": [
        ("CONC 5.2A.4R",     "Before entering into a regulated credit agreement for high-cost short-term credit, a firm must undertake a reasonable assessment of whether the customer will be able to repay the credit in a sustainable manner."),
        ("CONC 5.2A.5R",     "The creditworthiness assessment must take into account more than the likelihood that the customer will repay the credit, including the potential for the credit commitment to adversely impact the customer's financial situation."),
        ("CONC 5.2A.12R",    "A firm must not enter into a regulated credit agreement with a customer where the firm knows, or ought reasonably to conclude, that the customer is unable to repay without borrowing further."),
        ("CONC 5.2A.15R(2)", "A firm must consider whether the customer's repayment of the credit would have a significant adverse impact on the customer's financial situation."),
        ("CONC 2.5.3R",      "A firm must not attempt to create a false impression of a product or service in the customer's mind, including in relation to its suitability."),
    ],
    "credit_card": [
        ("CONC 5.2.1R",      "Before making a regulated credit agreement the firm must undertake a reasonable assessment of the creditworthiness of the customer."),
        ("CONC 5.2A.4R",     "The creditworthiness assessment must be based on sufficient information obtained from the customer and, where necessary, from a credit reference agency."),
        ("CONC 6.2.4R",      "A firm must monitor a customer's repayment record and take appropriate action where there are signs of financial difficulty or persistent debt."),
        ("CONC 6.7.27R",     "Before increasing a credit limit, a firm must undertake a fresh assessment of the customer's creditworthiness and affordability."),
        ("CONC 2.5.3R",      "A firm must not attempt to create a false impression of a product or service in the customer's mind, including in relation to its suitability."),
    ],
    "catalogue": [
        ("CONC 5.2.1R",      "Before making a regulated credit agreement the firm must undertake a reasonable assessment of the creditworthiness of the customer."),
        ("CONC 5.3.7G",      "In assessing creditworthiness, a firm should consider the customer's income, expenditure, and existing credit commitments."),
        ("CONC 5.2A.4R",     "The creditworthiness assessment must take into account the customer's ability to make repayments in a sustainable manner."),
        ("CONC 2.5.3R",      "A firm must not attempt to create a false impression of a product or service in the customer's mind."),
    ],
    "motor_finance": [
        ("CONC 5.2A.4R",     "Before entering into a regulated credit agreement, a firm must undertake a reasonable assessment of whether the customer will be able to repay in a sustainable manner without adversely impacting their financial situation."),
        ("CONC 5.2A.5R",     "The creditworthiness assessment must take into account the potential for the credit commitment to adversely impact the customer's financial situation, not merely the likelihood of repayment."),
        ("CONC 5.2A.12R",    "A firm must not enter into a regulated credit agreement where it knows, or ought reasonably to conclude, that the customer is unable to repay without borrowing further or without the repayments having a significant adverse impact on the customer's financial situation."),
        ("CONC 5.2A.15R(2)", "A firm must make a reasonable estimate of the customer's current income and consider whether repayments would have a significant adverse impact on the customer's financial situation."),
        ("CONC 2.5.3R",      "A firm must not attempt to create a false impression of a product or service in the customer's mind, including as to its suitability for the customer's financial circumstances."),
    ],
    "overdraft": [
        ("CONC 5.2.1R",                       "Before making a regulated credit agreement the firm must undertake a reasonable assessment of the creditworthiness of the customer."),
        ("CONC 5.2A.4R",                       "The creditworthiness assessment must consider whether the customer will be able to repay sustainably."),
        ("FCA Overdraft PS19/16, para 5.14",   "Firms must assess whether a customer is in, or at risk of, financial difficulty when that customer is using their overdraft frequently or approaching their limit."),
        ("BCOBS 5.1.12R",                      "A firm must treat customers in financial difficulty fairly."),
    ],
    "personal_loan": [
        ("CONC 5.2.1R",      "Before making a regulated credit agreement the firm must undertake a reasonable assessment of the creditworthiness of the customer."),
        ("CONC 5.2A.4R",     "The creditworthiness assessment must be based on sufficient information and must consider sustainable repayment."),
        ("CONC 5.2A.5R",     "The assessment must take into account the potential for the credit to adversely impact the customer's financial situation."),
        ("CONC 5.2A.15R(2)", "A firm must consider whether the customer's repayment of the credit would have a significant adverse impact on the customer's financial situation."),
        ("CONC 2.5.3R",      "A firm must not attempt to create a false impression of a product or service in the customer's mind."),
    ],
    "home_credit": [
        ("CONC 5.2A.4R",  "Before entering into a regulated credit agreement for high-cost credit, a firm must undertake a reasonable assessment of the customer's ability to repay sustainably."),
        ("CONC 5.2A.12R", "A firm must not enter into a regulated credit agreement where the firm knows, or ought reasonably to conclude, that the customer is unable to repay without borrowing further."),
        ("CONC 5.5.1R",   "A firm must not engage in irresponsible lending practices."),
        ("CONC 2.5.3R",   "A firm must not attempt to create a false impression of a product or service in the customer's mind."),
    ],
    "guarantor": [
        ("CONC 5.2.1R",  "Before making a regulated credit agreement the firm must undertake a reasonable assessment of the creditworthiness of both the borrower and the guarantor."),
        ("CONC 5.2A.4R", "The creditworthiness assessment must consider the ability of both parties to repay sustainably."),
        ("CONC 4.2.5R",  "A firm must provide a prospective guarantor with adequate pre-contract information to enable them to make an informed decision."),
    ],
    "other": [
        ("CONC 5.2.1R",  "Before making a regulated credit agreement the firm must undertake a reasonable assessment of the creditworthiness of the customer."),
        ("CONC 5.2A.4R", "The creditworthiness assessment must be based on sufficient information and must consider sustainable repayment."),
        ("CONC 2.5.3R",  "A firm must not attempt to create a false impression of a product or service in the customer's mind."),
    ],
}


LOC_ARGUMENT_FOCUS: dict[str, str] = {
    "payday": (
        "Our Client contends that {lender} failed to assess whether the loan was affordable and "
        "sustainable without the need to borrow further. The pattern of repeat short-term borrowing "
        "visible on the credit file at the time of lending demonstrates that our Client was already "
        "trapped in a cycle of debt dependency. Under FCA CONC 5.2A, {lender} was required to assess "
        "whether our Client could repay without undue difficulty and without the need to borrow "
        "further. It is our Client's position that no such assessment was conducted, or that any "
        "such assessment was disregarded in favour of completing the transaction."
    ),
    "credit_card": (
        "Our Client contends that {lender} failed to conduct a proportionate creditworthiness "
        "assessment prior to issuing and/or increasing the credit limit on the Agreement. The "
        "indicators of persistent balance reliance, escalating unsecured debt and repeat "
        "credit-seeking behaviour visible on the credit file at the time of lending ought to have "
        "prompted enhanced affordability scrutiny. Under CONC 6.2, responsible lenders must "
        "identify and act upon signs of persistent debt and minimum payment dependency. It is our "
        "Client's position that these indicators were either not identified or were disregarded."
    ),
    "catalogue": (
        "Our Client contends that {lender} failed to conduct proportionate affordability checks "
        "before extending revolving retail credit under the Agreement. The number of concurrent "
        "credit commitments and the sustained pattern of reliance on catalogue and revolving credit "
        "facilities at the time of lending indicates our Client was financially overextended. "
        "Under CONC 5.2 and 5.3, lenders must consider the totality of a customer's existing "
        "commitments before extending further credit, and should have identified the unsustainable "
        "nature of our Client's aggregate credit position."
    ),
    "motor_finance": (
        "Our Client contends that {lender} failed to conduct an adequate creditworthiness and "
        "affordability assessment prior to entering into the hire purchase or conditional sale "
        "agreement. The credit file available to {lender} at the date of the Agreement evidenced "
        "pre-existing financial commitments and, where applicable, adverse credit indicators. "
        "Under FCA CONC 5.2A, motor finance lenders are required to assess whether a customer "
        "can sustainably afford the monthly hire purchase payments without those payments having a "
        "significant adverse impact on their wider financial position. It is our Client's position "
        "that no adequate assessment was undertaken, or that the results of any such assessment "
        "were disregarded when approving the Agreement."
    ),
    "overdraft": (
        "Our Client contends that {lender} failed to recognise and act upon clear signs that our "
        "Client was in sustained financial difficulty as evidenced by persistent overdraft use. "
        "Under FCA overdraft pricing rules and BCOBS 5, banks are required to treat customers in "
        "financial difficulty fairly and to identify customers who are persistently reliant on "
        "their overdraft facility. It is our Client's position that {lender} failed to discharge "
        "this obligation and continued to extend overdraft credit without adequate affordability "
        "assessment."
    ),
    "personal_loan": (
        "Our Client contends that {lender} failed to carry out a full and meaningful affordability "
        "assessment prior to approving the loan. The volume of outstanding credit commitments and "
        "adverse markers visible on the credit file at the time of the application made it apparent "
        "that our Client was already over-committed and could not sustainably service additional "
        "debt. Under CONC 5.2A, a responsible lender would have identified this position and "
        "declined or subjected the application to enhanced scrutiny."
    ),
    "home_credit": (
        "Our Client contends that {lender} engaged in irresponsible lending by continuing to "
        "extend high-APR home credit despite clear evidence of financial stress visible on the "
        "credit file. The repeat lending cycle, combined with our Client's credit profile at the "
        "time of each Agreement, demonstrates a failure to conduct proportionate affordability "
        "checks as required under FCA CONC 5.2A and CONC 5.5."
    ),
    "guarantor": (
        "Our Client contends that {lender} failed to conduct adequate affordability assessments "
        "for both the primary borrower and guarantor as required under FCA CONC 5.2. The financial "
        "positions of both parties at the time of lending should have indicated that the loan was "
        "unaffordable, and that the guarantor's potential liability under the Agreement represented "
        "an unsustainable financial risk."
    ),
    "other": (
        "Our Client contends that {lender} failed to conduct adequate creditworthiness and "
        "affordability checks prior to extending credit under the Agreement. The financial profile "
        "visible on the credit report at the time of lending contained indicators of financial "
        "stress and existing commitments that should have resulted in the application being declined "
        "or subjected to enhanced scrutiny, as required under FCA CONC 5.2."
    ),
}


def get_conc_reference(lender_type: str) -> str:
    return CONC_REFERENCES.get(lender_type, CONC_REFERENCES["other"])


def get_conc_specific_rules(lender_type: str) -> list:
    return CONC_SPECIFIC_RULES.get(lender_type, CONC_SPECIFIC_RULES["other"])


def get_loc_argument(lender_type: str, lender_name: str) -> str:
    template = LOC_ARGUMENT_FOCUS.get(lender_type, LOC_ARGUMENT_FOCUS["other"])
    return template.format(lender=lender_name)
