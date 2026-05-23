#!/usr/bin/env python3
"""Pull a hand-picked subset from the dedup'd corpus into references.bib.

The selection list follows the six-pillar curation strategy and the
top-cited-by-pillar analysis from `scripts/analysis_outputs/`. Additionally
this script appends:

  * Manually-entered MCP gap-fillers (Terhart, Viebahn, Jones, Williams & Sembiante)
  * Ukrainian primary-source legislative entries (placeholders for §1, §3, §5 cites)
  * The Shulman/PCK foundational papers (KMK 2019, Shulman 1986/1987)

Output: ../references.bib
"""

from pathlib import Path

import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter

ROOT = Path(__file__).resolve().parents[1]
IN_BIB = ROOT / "data" / "corpus_filtered.bib"
OUT_BIB = ROOT / "references.bib"

# --- Curated keys to extract from the dedup'd corpus ---
CURATED_KEYS = {
    # Must-cite (top 10)
    "Baumert:2010:TeachersMathematical",
    "Guarino:2006:TeacherRecruitment",
    "Caena:2019:AligningTeacher",
    "Sutcher:2019:UnderstandingTeacher",
    "Cochransmith:2015:CritiquingTeacher",
    "Seidel:2014:ModelingMeasuring",
    "Koenig:2022:TeacherNoticing",
    "Forlin:2011:TeacherPreparation",
    "Angeli:2009:EpistemologicalMethodological",
    "Clark:1991:DualCoding",
    # PCK / content knowledge
    "Appleton:2003:BeginningPrimary",
    "Rienties:2013:EffectsOnline",
    "Scarino:2013:LanguageAssessment",
    "Blomberg:2011:ServiceTeachers",
    "Jang:2010:TpackDeveloping",
    "Mcneill:2013:TeachersPedagogical",
    "Girvan:2016:ExtendingExperiential",
    "Instefjord:2016:PreparingService",
    "Hogan:2003:RepresentationTeaching",
    "Newton:2008:ExtensivePreservice",
    # Comparative teacher ed
    "Freeman:2014:ServiceTeacher",
    "Dinkelman:2003:SelfTeacher",
    "Cochransmith:2013:PoliticsAccountability",
    "Furlong:2013:GlobalisationNeoliberalism",
    "Akyeampong:2017:TeacherEducators",
    "White:2019:TeacherEducators",
    "Harford:2010:TeacherEducation",
    "Beach:2013:ChangingProfessional",
    "Bales:2006:TeacherEducation",
    "Valeeva:2017:InitialTeacher",
    # Accreditation / quality assurance
    "Cox:2007:EffectsKnow",
    "Nelson:2019:MediatingFactors",
    "Cochransmith:2021:RethinkingTeacher",
    "Vare:2019:DevisingCompetence",
    "Dinham:2013:QualityTeaching",
    "Faez:2012:TesolTeacher",
    "Rowe:2019:CallingUrgent",
    "Harris:2010:CompetencyBased",
    "Deluca:2013:CurrentState",
    "Totenhagen:2016:RetainingEarly",
    "Odowd:2018:TrainingAccreditation",
    # Rural / labour market
    "Mcleskey:2008:DoesQuality",
    "Angrist:2008:DoesTeacher",
    "Ingersoll:2023:TeacherShortages",
    "Dupriez:2016:TeacherShortage",
    "Li:2020:ProblemsNeeds",
    "Damico:2017:WhereBlack",
    "Nguyen:2011:PrimaryEnglish",
    "Struyven:2013:TheyWant",
    "Yuan:2017:StudentTeachers",
    # History / continental tradition
    "Stengel:1997:AcademicDiscipline",
    "Goodwin:2010:CurriculumColonizer",
    "Engelbrecht:2015:EnactingUnderstanding",
    "Melnyk:2021:EstablishmentDevelopment",
    # Methods / systematic review
    "Chernikova:2020:SimulationBased",
    "Barrasso:2021:ScopingLiterature",
    "Schmid:2024:RunningCircles",
    "Cevikbas:2024:EmpiricalTeacher",
    "Norhagen:2024:DevelopingProfessional",
    # Dual-subject specific (sparse but present)
    "Proyer:2022:FirstForemost",
}


# --- Hand-entered gap-fillers (not in the WoS corpus) ---
EXTRA = r"""
@article{Terhart:2017:TeacherEducationGermany,
  author    = {Terhart, Ewald},
  title     = {Teacher Education in {Germany}},
  journal   = {Oxford Research Encyclopedia of Education},
  year      = {2017},
  publisher = {Oxford University Press},
  doi       = {10.1093/acrefore/9780190264093.013.377},
  note      = {Surveys the historical structure of German teacher preparation,
                including Hauptfach/Nebenfach combinations and the
                Staatsexamen system.},
}

@article{Viebahn:2003:TeacherEducationGermany,
  author    = {Viebahn, Peter},
  title     = {Teacher Education in {Germany}},
  journal   = {European Journal of Teacher Education},
  year      = {2003},
  volume    = {26},
  number    = {1},
  pages     = {87--100},
  doi       = {10.1080/0261976032000065661},
}

@article{Jones:2000:BecomingSecondary,
  author    = {Jones, Marion},
  title     = {Becoming a Secondary Teacher in {Germany}: A Trainee Perspective on Recent Developments in Initial Teacher Training},
  journal   = {Compare: A Journal of Comparative and International Education},
  year      = {2000},
  volume    = {30},
  number    = {1},
  pages     = {63--76},
  doi       = {10.1080/026197600411634},
}

@article{Williams:2022:ExperientialLearning,
  author    = {Williams, Lucas and Sembiante, Sabrina F.},
  title     = {Experiential Learning in {U.S.} Undergraduate Teacher Preparation Programs: A Review of the Literature},
  journal   = {Teaching and Teacher Education},
  year      = {2022},
  volume    = {112},
  pages     = {103630},
  doi       = {10.1016/j.tate.2022.103630},
}

@article{Goulding:2003:UndergraduateMathematics,
  author    = {Goulding, Maria and Hatch, Gillian and Rodd, Melissa},
  title     = {Undergraduate Mathematics Experience: Its Significance in Secondary Mathematics Teacher Preparation},
  journal   = {Journal of Mathematics Teacher Education},
  year      = {2003},
  volume    = {6},
  pages     = {361--393},
  doi       = {10.1023/A:1026362813351},
}

@article{Shulman:1986:ThoseWhoUnderstand,
  author    = {Shulman, Lee S.},
  title     = {Those Who Understand: Knowledge Growth in Teaching},
  journal   = {Educational Researcher},
  year      = {1986},
  volume    = {15},
  number    = {2},
  pages     = {4--14},
  doi       = {10.3102/0013189X015002004},
}

@article{Shulman:1987:KnowledgeBase,
  author    = {Shulman, Lee S.},
  title     = {Knowledge and Teaching: Foundations of the New Reform},
  journal   = {Harvard Educational Review},
  year      = {1987},
  volume    = {57},
  number    = {1},
  pages     = {1--22},
  doi       = {10.17763/haer.57.1.j463w79r56455411},
}

@misc{KMK:2019:Standards,
  author       = {{Kultusministerkonferenz}},
  title        = {Standards für die Lehrerbildung: Bildungswissenschaften (Beschluss vom 16.12.2004, i.d.F. vom 16.05.2019)},
  year         = {2019},
  organization = {Kultusministerkonferenz},
  address      = {Bonn},
  url          = {https://www.kmk.org/themen/allgemeinbildende-schulen/lehrkraefte/lehrerbildung.html},
}

@misc{Eurydice:2023:TeachersLifelongLearning,
  author       = {{European Commission, Eurydice}},
  title        = {Teachers in Europe: Careers, Development and Well-being},
  year         = {2023},
  organization = {Publications Office of the European Union},
  doi          = {10.2797/045401},
}

@misc{OECD:2020:TalisInsights,
  author       = {{OECD}},
  title        = {{TALIS} 2018 Results (Volume {II}): Teachers and School Leaders as Valued Professionals},
  year         = {2020},
  organization = {OECD Publishing},
  address      = {Paris},
  doi          = {10.1787/19cf08df-en},
}

@misc{Eurydice:2024:UkraineProfile,
  author       = {{European Commission, Eurydice}},
  title        = {Ukraine: National Education Systems},
  year         = {2024},
  organization = {European Commission},
  url          = {https://eurydice.eacea.ec.europa.eu/national-education-systems/ukraine/overview},
}

@misc{ZakonProVO:2014,
  author       = {{Verkhovna Rada of Ukraine}},
  title        = {On Higher Education {[}Про вищу освіту{]} -- Law {N}o.~1556-{VII}},
  year         = {2014},
  organization = {Verkhovna Rada of Ukraine},
  url          = {https://zakon.rada.gov.ua/laws/show/1556-18},
  note         = {Establishes the 25\% elective allocation in HE programmes; basis for the 45-ECTS deduction in the credit-architecture analysis.},
}

@misc{MON:Order1006,
  author       = {{Ministry of Education and Science of Ukraine}},
  title        = {Order No.~1006 of 11 November 2022: ``On Some Issues of Placement of State (Regional) Order, Combination of Specialities (Subject Specialities), Specialisations and Conferral of Professional Qualifications of Pedagogical Workers by Institutions of Vocational Pre-Higher and Higher Education''},
  year         = {2022},
  organization = {Ministry of Education and Science of Ukraine},
  note         = {Registered as z1669-22 on zakon.rada.gov.ua. Lost validity on 9 April 2024.},
  url          = {https://zakon.rada.gov.ua/laws/show/z1669-22},
}

@misc{MON:Order260,
  author       = {{Ministry of Education and Science of Ukraine}},
  title        = {Order No.~260 of 4 March 2024: ``On the Approval of the List of Subject Specialities of Speciality 014 Secondary Education (by Subject Specialities), Specialisations of Subject Speciality 014.02 Secondary Education (Language and Foreign Literature), Specialisations of Specialities 015 Vocational Education (by Specialisations) and 016 Special Education, for which State (Regional) Order Placement is Carried Out''},
  year         = {2024},
  organization = {Ministry of Education and Science of Ukraine},
  note         = {Registered as z0405-24 on zakon.rada.gov.ua. Replaces the subject-list portion of Order 1006/2022.},
  url          = {https://zakon.rada.gov.ua/laws/show/z0405-24},
}

@misc{MON:MethRecs2024,
  author       = {{Ministry of Education and Science of Ukraine}},
  title        = {Methodological Recommendations on the Development and Implementation of Educational Programmes in Higher Education},
  year         = {2024},
  organization = {Ministry of Education and Science of Ukraine},
  note         = {Non-binding successor regime to Order 1006/2022 after its rescission. URL to be added once the document is identified on mon.gov.ua.},
}

@misc{Eurydice:2025:UkraineBachelor,
  author       = {{European Commission, Eurydice}},
  title        = {Ukraine: Higher Education -- Bachelor's Programmes},
  year         = {2025},
  organization = {European Commission, Eurydice (Eurypedia)},
  note         = {``As of the beginning of 2024, Ukraine has established HESs for the Bachelor's degree programmes in almost all specialities, with the exception of 014 Secondary Education (by subject specialities).'' Last updated 14 August 2025.},
  url          = {https://eurydice.eacea.ec.europa.eu/eurypedia/ukraine/bachelor},
}

@misc{SQE:Certification2024,
  author       = {{State Service of Education Quality of Ukraine}},
  title        = {Results of Teacher Certification 2024: 1{,}478 teachers successfully certified},
  year         = {2024},
  organization = {Державна служба якості освіти України (SQE)},
  note         = {Categories tested in 2024: primary-school teachers, mathematics, Ukrainian language and literature, history and civic disciplines. English-language teachers were added to the certification cohort in 2026.},
  url          = {https://sqe.gov.ua/rezultaty-sertyfikaciji-2024/},
}

@misc{UCEQA:Calendar2024,
  author       = {{Ukrainian Centre for Educational Quality Assessment (UCEQA)}},
  title        = {Independent Testing of Teachers (Certification) -- 2024 Calendar},
  year         = {2024},
  organization = {Ukrainian Centre for Educational Quality Assessment (УЦОЯО)},
  url          = {https://testportal.gov.ua/sertyfikatsiya-2024-nezalezhne-testuvannya-vchyteliv-pochatkovyh-klasiv-matematyky-ta-ukrayinskoyi-movy-i-literatury/},
}

@misc{MON:Practicum,
  author       = {{Ministry of Education and Science of Ukraine}},
  title        = {Provisions on the Pedagogical Practicum in Teacher-Preparation Programmes},
  year         = {2014},
  note         = {Statutory 30-ECTS practicum requirement; cited in the credit-architecture table.},
}

@misc{ZakonBZD,
  author       = {{Verkhovna Rada of Ukraine}},
  title        = {On Civil Defence {[}Про захист населення і територій від надзвичайних ситуацій техногенного та природного характеру{]}},
  year         = {2000},
  note         = {Source of the BЖД (civil defence) credit requirement.},
}

@misc{MONIntegrity,
  author       = {{Ministry of Education and Science of Ukraine}},
  title        = {Recommendations on Integrating Anti-Corruption Competence into Higher-Education Programmes},
  year         = {2020},
  note         = {Source of the integrity / anti-corruption credit deduction.},
}

@misc{MONForeignLang,
  author       = {{Ministry of Education and Science of Ukraine}},
  title        = {Foreign-Language Competence Requirement in Higher Education},
  year         = {2018},
}

@misc{MONNationalSecurity,
  author       = {{Ministry of Education and Science of Ukraine}},
  title        = {National Security Doctrine in Higher-Education Curricula},
  year         = {2022},
}

@misc{MONPedagogyBlock,
  author       = {{Ministry of Education and Science of Ukraine}},
  title        = {Pedagogy and Psychology Component of Teacher-Preparation Programmes (60 {ECTS} block)},
  year         = {2020},
  note         = {The 60-ECTS pedagogy/psychology figure as advocated by Ukrainian accreditation expert groups.},
}

@misc{NAQA:2024:Standards,
  author       = {{National Agency for Higher Education Quality Assurance ({NAQA})}},
  title        = {Standards for Programme Accreditation: Teacher-Preparation Programmes},
  year         = {2024},
  organization = {NAQA Ukraine},
}
"""


def main():
    parser = BibTexParser(common_strings=True)
    parser.homogenize_fields = True
    with open(IN_BIB, encoding="utf-8") as f:
        db = bibtexparser.load(f, parser=parser)

    selected = []
    found = set()
    for e in db.entries:
        if e["ID"] in CURATED_KEYS:
            selected.append(e)
            found.add(e["ID"])

    missing = CURATED_KEYS - found
    if missing:
        print(f"[06] WARNING: {len(missing)} curated keys not found in corpus:")
        for k in sorted(missing):
            print(f"     - {k}")

    # Parse the EXTRA bibtex string and append
    parser2 = BibTexParser(common_strings=True)
    parser2.homogenize_fields = True
    extra_db = bibtexparser.loads(EXTRA, parser=parser2)
    selected.extend(extra_db.entries)

    out_db = bibtexparser.bibdatabase.BibDatabase()
    out_db.entries = sorted(selected, key=lambda x: x["ID"].lower())
    writer = BibTexWriter()
    writer.indent = "  "
    writer.add_trailing_comma = True
    with open(OUT_BIB, "w", encoding="utf-8") as fh:
        fh.write(writer.write(out_db))
    print(f"[06] Wrote {OUT_BIB} ({len(out_db.entries)} entries: "
          f"{len(selected) - len(extra_db.entries)} from corpus + {len(extra_db.entries)} hand-entered)")


if __name__ == "__main__":
    main()
