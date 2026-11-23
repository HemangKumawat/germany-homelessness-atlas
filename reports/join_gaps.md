# Join gaps

Generated 2026-11-23T18:57:07+00:00 from data/atlas.db (`python3 -m scripts.join_gaps`; also after every ingest run).
Organisation-level data and published roles only: no person names, no addresses.

| check | count |
|---|---|
| orgs (rows) / canonical / alias rows | 1079 / 1055 / 24 |
| org_link rows by method | manual 39, name_fuzzy 47, origin 1714, register_id 1332, ust_id 83 |
| canonical orgs with awards but no register id | 131 |
| land: with zaehlung/metric counts but no population | 0 |
| land: zaehlung years without population (Y or Y-1) | 0 |
| kreis: with zaehlung/metric counts but no population | 0 |
| kreis: zaehlung years without population (Y or Y-1) | 0 |
| gemeinde: with zaehlung/metric counts but no population | 0 |
| gemeinde: zaehlung years without population (Y or Y-1) | 0 |
| org_person rows without a valid org link | 0 |
| duplicate candidates: same hard id on >1 canonical org | 0 |
| duplicate candidates: same register number, court differs or not stated | 0 |
| duplicate candidates: name similarity ≥ 0.9 + same Land + same legal form | 12 |
| duplicate candidates: same normalised name, different Land | 6 |
| fuzzy (name-only) links awaiting review | 47 |
| awards whose USt-IdNr belongs to another canonical org (VAT group? review) | 0 |

## Same hard id on more than one canonical org (G11a fails on these) (0)

None.

## Orgs with awards but no register id (131)

| org | Land | source system | awards | sum EUR | USt-IdNr |
|---|---|---|---|---|---|
| #701 Diakonisches Werk Hamburg - Landesverband der Inneren Mission e.V. | HH | domain:funding_hamburg | 57 | 16.474.873 | no |
| #704 Caritasverband für das Erzbistum Hamburg e.V. | HH | domain:funding_hamburg | 28 | 8.243.759 | no |
| #115 five walls GmbH | BY | ted | 15 | 0 | yes |
| #116 European Homecare GmbH | NW | ted | 13 | 26.965.920 | yes |
| #1069 Verein für Innere Mission in Bremen | HB | domain:funding_manual | 13 | 1.429.639 | no |
| #702 Basis & Woge e.V. | HH | domain:funding_hamburg | 11 | 2.678.164 | no |
| #705 Kemenate Frauen Wohnen e.V. | HH | domain:funding_hamburg | 11 | 3.654.034 | no |
| #716 STREETLIFE - Verein für Straßensozialarbeit in Hamburg e.V. | HH | domain:funding_hamburg | 10 | 2.003.382 | no |
| #128 Jonas Better Place GmbH | BY | ted | 6 | 0 | yes |
| #121 Internationaler Bund (IB) IB Berlin-Brandenburg gGmbH | BB | ted | 5 | 0 | yes |
| #706 Palette gGmbH für akzeptierende soziale Hilfen | HH | domain:funding_hamburg | 5 | 546.297 | no |
| #714 MW Malteser Werke gemeinnützige GmbH | HH | domain:funding_hamburg | 5 | 6.981.717 | no |
| #722 PALETTE Hamburg e.V. | HH | domain:funding_hamburg | 5 | 176.523 | no |
| #164 jhj Hamburg e.V | HH | ted | 4 | 2.992.000 | no |
| #709 Evangelische Stiftung der Bodelschwingh- Gemeinde | HH | domain:funding_hamburg | 4 | 356.808 | no |
| #726 Die Mission. Künstlerische Maßnahmen gegen die Kälte e.V. | HH | domain:funding_hamburg | 4 | 25.300 | no |
| #117 AWO Hamburg Seniorenwohnen&Pflege gGmbH | HH | ted | 3 | 0 | no |
| #169 das BOOT gGmbH Sozialpsychiatrisches Zentrum | SN | ted | 3 | 0 | yes |
| #187 S.W.S. Schnock GmbH | NW | ted | 3 | 0 | yes |
| #208 Lectus München GmbH | BY | ted | 3 | 0 | no |
| #707 CVJM zu Hamburg e.V. Christlicher Verein Junger Menschen | HH | domain:funding_hamburg | 3 | 7.600 | no |
| #721 Christlicher Verein Junger Menschen, Landesverband Hamburg e.V. | HH | domain:funding_hamburg | 3 | 4.700 | no |
| #724 F&W Fördern & Wohnen AöR | HH | domain:funding_hamburg | 3 | 3.000 | no |
| #1067 Caritasverband Bremen e.V. | HB | domain:funding_manual | 3 | 105.122 | no |
| #1070 Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V. | HB | domain:funding_manual | 3 | 1.065 | no |
| #1074 Die Bremer Suppenengel e.V. | HB | domain:funding_manual | 3 | 40.000 | no |
| #1077 Hoppenbank e.V. | HB | domain:funding_manual | 3 | 745.897 | no |
| #140 Caritasverband für den Bezirk Hochtaunus e. V. | HE | ted | 2 | 719.129 | no |
| #160 objekta gebäudeservice und dienstleistungs gmbh | BY | ted | 2 | 0 | no |
| #167 Ev.-Luth. Kirchenkreis Hamburg Ost | HH | ted | 2 | 2.992.000 | no |
| #170 AWO Unterbezirk Ruhr-Mitte | NW | ted | 2 | 0 | no |
| #180 SKM Augsburg e. V. | BY | ted | 2 | 9.030.571 | yes |
| #181 Sozialdienst Kath. Frauen e. V. | BY | ted | 2 | 2.108.350 | yes |
| #194 hotel Ahorn | BY | ted | 2 | 0 | no |
| #225 Thomas Wolter GmbH | SN | ted | 2 | 0 | yes |
| #235 HORIZONT e.V. | BY | ted | 2 | 0 | yes |
| #710 Streetlife e.V. Verein für Straßensozialarbeit in | HH | domain:funding_hamburg | 2 | 355.390 | no |
| #711 Anstoß! Bundesvereinigung für Soziale Integration durch Sport | HH | domain:funding_hamburg | 2 | 48.200 | no |
| #715 Ev.-luth. Kirchengemeinde Eimsbüttel | HH | domain:funding_hamburg | 2 | 226.784 | no |
| #723 GoBanyo gGmbH | HH | domain:funding_hamburg | 2 | 61.035 | no |
| #725 Verein zur Förderung der Jugendarbeit e.V. | HH | domain:funding_hamburg | 2 | 406.949 | no |
| #727 Caritasstiftung Hamburg e.V. | HH | domain:funding_hamburg | 2 | 85.500 | no |
| #729 Deutscher Paritätischer Wohlfahrtsverband Landesverband Mecklenburg-Vorpommern e.V. | MV | domain:funding_mv | 2 | 34.000 | no |
| #1068 Housing First Bremen gemeinnützige UG (haftungsbeschränkt) | HB | domain:funding_manual | 2 | 644.272 | no |
| #1071 Klinikum Bremerhaven-Reinkenheide gGmbH | HB | domain:funding_manual | 2 | 149.775 | no |
| #1073 Diakonisches Werk Bremen e.V. | HB | domain:funding_manual | 2 | 6.000 | no |
| #1075 Verein zur Förderung der medizinischen Versorgung Obdachloser im Lande Bremen e.V. | HB | domain:funding_manual | 2 | 97.500 | no |
| #119 pem. Personalentwicklungs- und -management GmbH | ST | ted | 1 | 836.496 | no |
| #123 Soziales Zentrum e. V. | NW | ted | 1 | 5.829.633 | no |
| #124 Objekta Dienstleistungs GmbH | BY | ted | 1 | 5.760.000 | no |
| #125 Comtact GmbH | MV | ted | 1 | 0 | no |
| #127 wohnen & betreuen | NI | ted | 1 | 0 | no |
| #129 Diakonisches Werk e. V. | HE | ted | 1 | 240.000 | no |
| #132 Clearingstelle und Anonymer Behandlungsschein Leipzig e.V. | SN | ted | 1 | 0 | no |
| #133 Dornahof Integrationsbetriebe gGmbH | BW | ted | 1 | 0 | no |
| #134 PaSo gGmbH | HE | ted | 1 | 1.580.033 | no |
| #135 Stephanus Stiftung | BE | ted | 1 | 1.705.729 | no |
| #138 Solidarische Psychosoziale Hilfe Hamburg e. V. | HH | ted | 1 | 1.000.000 | no |
| #139 Deutsches Rotes Kreuz Kreisverband Hochtaunus e. V. | HE | ted | 1 | 1.324.327 | no |
| #142 Verein für Berliner Stadtmission, Lehrter Straße 68, 10557 Berlin | BE | ted | 1 | 0 | no |
| #143 Deutsches Rotes Kreuz Kreisverband Wetzlar e.V. | HE | ted | 1 | 0 | no |
| #144 Deutsches Rotes Kreuz Kreisverband Dillenburg e.V. | HE | ted | 1 | 0 | no |
| #145 Malteser Hilfsdienst gGmbH | HE | ted | 1 | 0 | no |
| #146 Deutsches Rotes Kreuz Soziale Dienste gGmbH | NW | ted | 1 | 3.090.270 | no |
| #150 Diakonie München und Oberbayern gGmbH | BY | ted | 1 | 0 | yes |
| #151 Johanniter-Unfall-Hilfe e. V. | SH | ted | 1 | 0 | no |
| #152 Deutsches Rotes Kreuz Betreuungsdienste Lübeck gGmbH | SH | ted | 1 | 0 | no |
| #153 Bildungszentrum Blume GmbH | NW | ted | 1 | 226.800 | yes |
| #155 ASB Sozialeinrichtungen (Hamburg) GmbH Zuwanderer- und Wohnungslosenhilfe | HH | ted | 1 | 0 | no |
| #156 Complete Dienstleistung GmbH | HH | ted | 1 | 0 | no |
| #157 MW Malteser Werke gGmbH | NW | ted | 1 | 0 | no |
| #158 Teller Voll GmbH | BY | ted | 1 | 0 | no |
| #159 Sikas GmbH | BY | ted | 1 | 0 | no |
| #161 AWO Bezirksverband Potsdam e. V. | BB | ted | 1 | 0 | no |
| #171 DRK Kreisverband Bremervörde e.V. | NI | ted | 1 | 1.421.000 | no |
| #172 AST-Bildung GmbH | NW | ted | 1 | 0 | no |
| #173 Norddeutsche Gesellschaft für Diakonie mbH | SH | ted | 1 | 0 | yes |
| #175 Arbeiter-Samariter-Bund | NI | ted | 1 | 0 | no |
| #176 Hero Zukunft GmbH | BE | ted | 1 | 0 | no |
| #178 Deutsches Rotes Kreuz Ortsverein Detmold e.V. | NW | ted | 1 | 0 | no |
| #179 Arbeiter-Samariter-Bund Regionalverband Ostwestfalen-Lippe e.V. | NW | ted | 1 | 0 | no |
| #184 milaa gGmbH, Boyenstraße 42, 10115 Berlin | BE | ted | 1 | 0 | no |
| #185 Volkssolidarität Landesverband Berlin e. V., Storkower Straße 111, 10407 Berlin | BE | ted | 1 | 0 | no |
| #186 INDUTEC Industrieservice GmbH | NW | ted | 1 | 0 | no |
| #191 Evangelische Gesellschaft Stuttgart e.V. | BW | ted | 1 | 0 | no |
| #193 ASB Neubrandenburg gGmbH | MV | ted | 1 | 1.002.477 | no |
| #195 SZL Suchtzentrum gGmbH | SN | ted | 1 | 0 | no |
| #197 Bayern GmbH Star Inn Hotel München Schwabing, by Comfort | BY | ted | 1 | 0 | no |
| #200 Wäscherei Henke GmbH&Co.KG | NI | ted | 1 | 0 | no |
| #203 Diakoniewerk im nördlichen Mecklenburg gGmbH | MV | ted | 1 | 2.320.815 | no |
| #206 Heinzelmännchen Gebäudereinigungs GmbH | NW | ted | 1 | 0 | no |
| #207 Rösch GmbH & CO.KG | BY | ted | 1 | 0 | no |
| #209 DRK Flüchtlingshilfe Westfalen-Lippe gGmbH | NW | ted | 1 | 0 | no |
| #211 IB Berlin — Brandenburg GmbH, Region Brandenburg Südost | BB | ted | 1 | 2.068.856 | no |
| #212 ASB - Arbeiter-Samariter-Bund Landesverband Niedersachsen e.V. Kreisverband Hannover-Land/Schaumburg | NI | ted | 1 | 0 | no |
| #213 Tamaja Betreuung und Beherbergung gemeinnützige GmbH | BE | ted | 1 | 5.444.464 | yes |
| #214 H&H Verwaltung GmbH | BY | ted | 1 | 0 | no |
| #216 WOM SECURITY & SERVICE GMBH | HE | ted | 1 | 0 | no |
| #217 RWS Security GmbH | HE | ted | 1 | 0 | no |
| #220 ABC Kochwerk Bremen GmbH | NI | ted | 1 | 15.000.000 | no |
| #222 Johanniter-Unfall-Hilfe e.V. | NW | ted | 1 | 0 | yes |
| #223 Arbeiter-Samariter-Bund RV Mittleres Westfalen e.V. | NW | ted | 1 | 3.927 | no |
| #228 Diakonisches Werk Hamburg-West / Südholstein | HH | ted | 1 | 900.000 | no |
| #229 Arbeiterwohlfahrt - Soz. Dienste Chemnitz und Umgebung gGmbH | SN | ted | 1 | 0 | no |
| #230 DRK Kreisverband Börde e.V. | ST | ted | 1 | 0 | no |
| #231 ORS Deutschland GmbH | BW | ted | 1 | 0 | yes |
| #232 Arbeiter-Samariter-Bund RV Ostwestfalen-Lippe e. V. | NW | ted | 1 | 0 | no |
| #233 Deutsches Rotes Kreuz Hamburg Altona und Mitte e.V. | HH | ted | 1 | 0 | no |
| #234 Internationaler Bund Mitte gGmbH | ST | ted | 1 | 0 | yes |
| #236 Meglingerstraße Appartement-Haus GmbH | BY | ted | 1 | 0 | no |
| #237 Reisingerstraße Appartement- Haus GmbH | BY | ted | 1 | 0 | no |
| #238 Schöllstraße Appartement- Haus GmbH (Neubau) | BY | ted | 1 | 0 | no |
| #239 Hotelbetriebsgesellschaft M. u. C. Lehmann-Horn mbH | BY | ted | 1 | 0 | yes |
| #240 BEWA Security GmbH | NW | ted | 1 | 1.551.428 | yes |
| #241 AWO KV Oberlausitz e.V. | SN | ted | 1 | 1.973.970 | no |
| #242 Boutique-Hotel Goethe GmbH | BY | ted | 1 | 0 | yes |
| #243 Evangelisch-Lutherischer Kirchenkreis Hamburg-Ost | HH | ted | 1 | 0 | no |
| #682 Malteser Hilfsdienst e.V. | BW | ted | 1 | 1.343.000 | no |
| #703 Ev.Stiftung Bodelschwingh-Gemeinde | HH | domain:funding_hamburg | 1 | 221.154 | no |
| #708 Die Heilsarmee in Deutschland Körperschaft des öffentlichen Rechts | HH | domain:funding_hamburg | 1 | 42.767 | no |
| #712 Quadriga gemeinnützige Gesellschaft für Beratung, Jugend, Kultur und Arbeit mbH | HH | domain:funding_hamburg | 1 | 7.000 | no |
| #713 Hunde-Lobby e.V. | HH | domain:funding_hamburg | 1 | 2.291 | no |
| #717 Stiftung TO HUUS | HH | domain:funding_hamburg | 1 | 193.639 | no |
| #718 Urban Art Institute Hamburg e.V. | HH | domain:funding_hamburg | 1 | 13.485 | no |
| #719 Leben im Abseits e.V. | HH | domain:funding_hamburg | 1 | 11.773 | no |
| #720 CAFÉE mit Herz e.V. | HH | domain:funding_hamburg | 1 | 1.300 | no |
| #728 Malteser Hilfsdienst e.V. | HH | domain:funding_hamburg | 1 | 1.500 | no |
| #1072 Caritasverband für Bremen-Nord, Bremerhaven und die Landkreise Cuxhaven und Osterholz e.V. | HB | domain:funding_manual | 1 | 29.900 | no |
| #1076 Bremer Werkgemeinschaft GmbH | HB | domain:funding_manual | 1 | 127.550 | no |
| #1078 comeback gemeinnützige GmbH | HB | domain:funding_manual | 1 | 203.100 | no |
| #1079 Prot. Kirchenbezirk Ludwigshafen | RP | domain:funding_manual | 1 | 1.000 | no |

## Land: counts but no population (0)

None.

## Land: zaehlung years without a population for Y or Y-1 (0)

None.

## Kreis: counts but no population (0)

None.

## Kreis: zaehlung years without a population for Y or Y-1 (0)

None.

## Gemeinde: counts but no population (0)

None.

## Gemeinde: zaehlung years without a population for Y or Y-1 (0)

None.

## org_person rows without a valid org link (0)

None.

## Same register number, court differs or not stated (review; never merged automatically) (0)

None.

## Name similarity ≥ 0.9, same Land and legal form (review) (12)

| org A | org B | Land | legal form | similarity |
|---|---|---|---|---|
| #236 Meglingerstraße Appartement-Haus GmbH | #237 Reisingerstraße Appartement- Haus GmbH | BY | GmbH | 0.909 |
| #676 Koordination Wohnungslosenhilfe Nordbayern | #677 Koordination Wohnungslosenhilfe Südbayern | BY |  | 0.929 |
| #157 MW Malteser Werke gGmbH | #219 Malteser Werke gGmbH | NW | gGmbH | 0.903 |
| #206 Heinzelmännchen Gebäudereinigungs GmbH | #215 Heinzelmännchen Gebäudereinigung GmbH | NW | GmbH | 0.986 |
| #710 Streetlife e.V. Verein für Straßensozialarbeit in | #716 STREETLIFE - Verein für Straßensozialarbeit in Hamburg e.V. | HH | e.V. | 0.905 |
| #729 Deutscher Paritätischer Wohlfahrtsverband Landesverband Mecklenburg-Vorpommern e.V. | #764 Der Paritätische Wohlfahrtsverband Landesverband Mecklenburg – Vorpommern e.V. | MV | e.V. | 0.925 |
| #740 DLRG e.V. - Landesverband Mecklenburg-Vorpommern | #774 DRK-Landesverband Mecklenburg-Vorpommern e.V. | MV | e.V. | 0.963 |
| #740 DLRG e.V. - Landesverband Mecklenburg-Vorpommern | #787 ASB Landesverband Mecklenburg-Vorpommern e.V. | MV | e.V. | 0.914 |
| #747 Sehrrahner Diakoniewerk gGmbH | #911 Serrahner Diakoniewerk gemeinnützige GmbH | MV | gGmbH | 0.978 |
| #774 DRK-Landesverband Mecklenburg-Vorpommern e.V. | #787 ASB Landesverband Mecklenburg-Vorpommern e.V. | MV | e.V. | 0.925 |
| #828 Deutsches Rotes Kreuz Kreisverband Schwerin e.V. | #1045 Deutsches Rotes Kreuz Kreisverband Demmin | MV | e.V. | 0.905 |
| #837 Arbeiterwohlfahrt Regionalverband Demmin e.V. | #842 Arbeiterwohlfahrt Regionalverband Rügen e.V. | MV | e.V. | 0.9 |

## Same normalised name in different Länder (review) (6)

| normalised name | orgs (Land, ort) |
|---|---|
| BUNDESARBEITSGEMEINSCHAFT WOHNUNGSLOSENHILFE | #19 Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V. (BE, Berlin); #1070 Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V. (HB, -) |
| CARITASVERBAND ERZBISTUM HAMBURG | #704 Caritasverband für das Erzbistum Hamburg e.V. (HH, -); #1019 Caritasverband für das Erzbistum Hamburg e.V. (MV, -) |
| JOHANNITER UNFALL HILFE | #62 Johanniter-Unfall Hilfe e. V. (BE, Berlin); #151 Johanniter-Unfall-Hilfe e. V. (SH, Lübeck); #222 Johanniter-Unfall-Hilfe e.V. (NW, Neuss) |
| MALTESER HILFSDIENST | #145 Malteser Hilfsdienst gGmbH (HE, Limburg a.d. Lahn); #162 Malteser Hilfsdienst gGmbH (BW, Stuttgart); #658 Malteser Hilfsdienst e.V. (-, Köln); #682 Malteser Hilfsdienst e.V. (BW, Freiburg i. Br.); #728 Malteser Hilfsdienst e.V. (HH, -) |
| MW MALTESER WERKE | #157 MW Malteser Werke gGmbH (NW, Köln); #714 MW Malteser Werke gemeinnützige GmbH (HH, -) |
| VSP VERBUND SOZIALE PROJEKTE | #810 VSP- Verbund für Soziale Projekte gemeinnützige GmbH (MV, -); #865 VSP \| Verbund für Soziale Projekte e.V. (MV, -) |

## Fuzzy (name-only) links awaiting review (47)

| record | name in record | linked to | confidence | note |
|---|---|---|---|---|
| institutions_media_org BUNDESARBEITSGEMEINSCHAFT WOHNUNGSLOSENHILFE\|DE\|https://www.bagw.de/de/bag-w/mitgliedschaft | Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V. | #19 Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V. | 0.9 | name step: exact (name_norm + legal form + Land, INGEST_CONTRACT §12) |
| lobbyregister R004197 | Klinikum Frankfurt (Oder) GmbH | #698 Klinikum Frankfurt (Oder) | 0.9 | same normalised name and legal form, no conflicting register id |
| mv_tdb_traeger mv_tdb:6ab2840c-effa-11ed-9c16-005056bc6a4b | Kindertagesstätten „St. Spiritus“ Pasewalk gGmbH | #996 Kindertagesstätten "St. Spiritus" Pasewalk gGmbH | 0.9 | name step: exact (name_norm + legal form + Land, INGEST_CONTRACT §12) |
| mv_tdb_traeger mv_tdb:cc25dfc8-8cbe-11f0-8e4e-005056bc3816 | DRK-Kreisverband Nordvorpommern e.V. | #819 DRK Kreisverband Nordvorpommern e.V. | 0.9 | name step: exact (name_norm + legal form + Land, INGEST_CONTRACT §12) |
| mv_tdb_traeger mv_tdb:f362bf04-ecf8-11ea-a276-005056bc6a4b | Behindertenverband e. V. Grevesmühlen | #775 Behindertenverband e. V. Grevesmühlen | 0.9 | name step: exact (name_norm + legal form + Land, INGEST_CONTRACT §12) |
| award DE-HB-ZEBRA:021/077-016-11-08/2026 | Hoppenbank e.V. | #1077 Hoppenbank e.V. | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/BAG-W/2025 | Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V. | #1070 Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V. | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/BAG-W/2026 | Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V. | #1070 Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V. | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/Bahnh.miss VIM/2026 | Verein für Innere Mission in Bremen | #1069 Verein für Innere Mission in Bremen | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/Caritas.Bhfmiss/2026 | Caritasverband Bremen e.V. | #1067 Caritasverband Bremen e.V. | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/Gewopro/2026 | Verein für Innere Mission in Bremen | #1069 Verein für Innere Mission in Bremen | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/HoFI Akquise/2025 | Verein für Innere Mission in Bremen | #1069 Verein für Innere Mission in Bremen | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/Housing First/2026 | Hoppenbank e.V. | #1077 Hoppenbank e.V. | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/Kälteregelung/2025 | Verein für Innere Mission in Bremen | #1069 Verein für Innere Mission in Bremen | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/Kälteregelung/2026 | Verein für Innere Mission in Bremen | #1069 Verein für Innere Mission in Bremen | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/KälteregelungII/2025 | Verein für Innere Mission in Bremen | #1069 Verein für Innere Mission in Bremen | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/Notschlafst.FRS/2025 | Verein für Innere Mission in Bremen | #1069 Verein für Innere Mission in Bremen | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/Notschlafst.FRS/2026 | Verein für Innere Mission in Bremen | #1069 Verein für Innere Mission in Bremen | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02/Suppenengel/2026 | Die Bremer Suppenengel e.V. | #1074 Die Bremer Suppenengel e.V. | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/3-02Erfrierungsschut/2026 | Verein für Innere Mission in Bremen | #1069 Verein für Innere Mission in Bremen | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/431/Caritas.Bhfmiss/2025 | Caritasverband Bremen e.V. | #1067 Caritasverband Bremen e.V. | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/431/Housing First/2025 | Housing First Bremen gemeinnützige UG (haftungsbeschränkt) | #1068 Housing First Bremen gemeinnützige UG (haftungsbeschränkt) | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/431/Suppenengel/2025 | Die Bremer Suppenengel e.V. | #1074 Die Bremer Suppenengel e.V. | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/431/VIM/Bahnhofsmiss/2025 | Verein für Innere Mission in Bremen | #1069 Verein für Innere Mission in Bremen | 0.95 | same normalised name |
| award DE-HB-ZEBRA:400/4S3/PfDMitteMaW/2025 | Diakonisches Werk Bremen e.V. | #1073 Diakonisches Werk Bremen e.V. | 0.95 | same normalised name |
| award DE-HB-ZEBRA:500/KBR - Nachtcafé/2025 | Klinikum Bremerhaven-Reinkenheide gGmbH | #1071 Klinikum Bremerhaven-Reinkenheide gGmbH | 0.95 | same normalised name |
| award DE-HB-ZEBRA:500/MVO_Pandemiefolgen/2025 | Verein zur Förderung der medizinischen Versorgung Obdachloser im Lande Bremen e.V. | #1075 Verein zur Förderung der medizinischen Versorgung Obdachloser im Lande Bremen e.V. | 0.95 | same normalised name |
| award DE-HH-ZUW:SF-098036 | Deutsches Rotes Kreuz, Kreisverband Hamburg-Harburg e.V. | #154 Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V. | 0.95 | same normalised name |
| award DE-HH-ZUW:SF-105039 | Deutsches Rotes Kreuz, Kreisverband Hamburg-Harburg e.V. | #154 Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V. | 0.95 | same normalised name |
| award DE-HH-ZUW:ZUW-2023-01549 | Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V. | #154 Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V. | 0.95 | same normalised name |
| award DE-HH-ZUW:ZUW-2024-01700 | Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V. | #154 Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V. | 0.95 | same normalised name |
| award DE-HH-ZUW:ZUW-2025-03341 | Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V. | #154 Deutsches Rotes Kreuz Kreisverband Hamburg-Harburg e.V. | 0.95 | same normalised name |
| award TED:23601-2023:ITEM-1:GEBEWO PRO | GEBEWO pro GmbH | #47 GEBEWO pro gGmbH | 0.95 | same normalised name |
| award TED:383141-2020:ITEM-1:EUROPEAN HOMECARE | European Homecare GmbH | #116 European Homecare GmbH | 0.95 | same normalised name |
| award TED:39545-2021:ITEM-1:EUROPEAN HOMECARE | European Homecare GmbH | #116 European Homecare GmbH | 0.95 | same normalised name |
| award TED:410233-2016:ITEM-1:EUROPEAN HOMECARE | European Homecare GmbH | #116 European Homecare GmbH | 0.95 | same normalised name |
| award TED:467003-2022:ITEM-1:FIVE WALLS | five walls GmbH | #115 five walls GmbH | 0.95 | same normalised name |
| award TED:467003-2022:ITEM-2:FIVE WALLS | five walls GmbH | #115 five walls GmbH | 0.95 | same normalised name |
| award TED:467003-2022:ITEM-3:FIVE WALLS | five walls GmbH | #115 five walls GmbH | 0.95 | same normalised name |
| award TED:467003-2022:ITEM-4:FIVE WALLS | five walls GmbH | #115 five walls GmbH | 0.95 | same normalised name |
| award TED:467003-2022:ITEM-5:FIVE WALLS | five walls GmbH | #115 five walls GmbH | 0.95 | same normalised name |
| award TED:467003-2022:ITEM-6:FIVE WALLS | five walls GmbH | #115 five walls GmbH | 0.95 | same normalised name |
| award TED:467003-2022:ITEM-7:FIVE WALLS | five walls GmbH | #115 five walls GmbH | 0.95 | same normalised name |
| award TED:530470-2022:ITEM-1:HOTEL AHORN | Hotel Ahorn | #194 hotel Ahorn | 0.95 | same normalised name |
| award TED:630717-2022:ITEM-1:STIFTUNG FOERDERUNG SOZIALER DIENSTE FSD STIFTUNG | Stiftung zur Förderung sozialer Dienste (FSD-Stiftung) | #98 Stiftung zur Förderung sozialer Dienste (FSD-Stiftung) | 0.95 | same normalised name |
| award TED:630717-2022:ITEM-2:VEREIN BERLINER STADTMISSION | Verein für Berliner Stadtmission | #14 Berliner Stadtmission e. V. | 0.95 | same normalised name |
| award TED:92531-2017:ITEM-4:JHJ HAMBURG | jhj Hamburg e.V. | #164 jhj Hamburg e.V | 0.95 | same normalised name |

## Awards whose recipient USt-IdNr belongs to another canonical org (review; a VAT group shares one number) (0)

None.

## Alias rows merged into a canonical org (24)

| alias | canonical | method | reason |
|---|---|---|---|
| #114 ZIK - zuhause im Kiez gGmbH | #1 "zuhause im Kiez" zik Gesellschaft zur besseren Wohnraumversorgung für Kranke und Hilfsbedürftige mbH | register_id | same hard id BE_ZUWDB:hrb_031751 as #1 (deterministic hard-id merge) |
| #8 Arbeiterwohlfahrt Kreisverband Berlin Spree-Wuhle e. V. | #7 Arbeiterwohlfahrt Berlin Spree-Wuhle e. V. | register_id | same hard id BE_ZUWDB:vr_021507 as #7 (deterministic hard-id merge) |
| #11 AWO Kreisverband Berlin Mitte e. V. | #10 AWO Arbeiterwohlfahrt Kreisverband Berlin-Mitte e. V. | register_id | same hard id BE_ZUWDB:vr_010713 as #10 (deterministic hard-id merge) |
| #110 Verein für Berliner Stadtmission | #14 Berliner Stadtmission e. V. | register_id | same hard id BE_ZUWDB:vr_024148 as #14 (deterministic hard-id merge) |
| #648 Bundesarbeitsgemeinschaft Wohnungslosenhilfe e.V. | #19 Bundesarbeitsgemeinschaft Wohnungslosenhilfe e. V. | manual | Lead review (docs/org_merges.tsv): same name and legal form (e.V.); BAG W is one national association seated in Berlin (#19: Berlin Zuwendungsdatenbank + Lobbyregister R001487); #648 is the BAG W membership page with Land 'DE' and no seat |
| #28 DRK Berlin Südwest Soziale Arbeit, Beratung und Bildung | #22 Deutsches Rotes Kreuz Berlin Südwest Soziale Arbeit, Beratung und Bildung | register_id | same hard id BE_ZUWDB:hrb_095332 as #22 (deterministic hard-id merge) |
| #38 Evangelische Kirchengemeinde St. Petri - St. Marien | #37 Evangelische Kirchengemeinde St. Marien-Friedrichswerder | register_id | same hard id BE_ZUWDB:kör_100064 as #37 (deterministic hard-id merge) |
| #43 Fixpunktgemeinnützige Gesellschaft für Gesundheitsförderung und sozialintegrierende Hilfen für Suchtmittelabhängige mbH | #41 Fixpunkt - gemeinnützige Gesellschaft für Gesundheitsförderung und sozialintegrierende Hilfen für Suchtmittelabhängige mbH | register_id | same hard id BE_ZUWDB:hrb_082787 as #41 (deterministic hard-id merge) |
| #46 GANGWAY - Straßensozialarbeit in Berlin | #45 Gangway | register_id | same hard id BE_ZUWDB:vr_010473 as #45 (deterministic hard-id merge) |
| #56 Humanistischer Verband Deutschlands, Landesverband Berlin-Brandenburg KdöR | #55 Humanistischer Verband Deutschland, Landesverband Berlin-Brandenburg KdöR | register_id | same hard id BE_ZUWDB:kör_100199 as #55 (deterministic hard-id merge) |
| #61 Internationaler Bund - IB Berlin-Brandenburg gGmbH für Bildung und soziale Dienste (IB Berlin-Brandenburg gGmbH) | #57 IB Berlin-Brandenburg gGmbH Region Berlin Südwest | register_id | same hard id BE_ZUWDB:nr_100309 as #57 (deterministic hard-id merge) |
| #63 Johanniter-Unfall Hilfe e. V. Regionalverband Berlin | #62 Johanniter-Unfall Hilfe e. V. | register_id | same hard id BE_ZUWDB:vr_017661 as #62 (deterministic hard-id merge) |
| #69 Katholische Kirchengemeinde St. Marien Berlin-Wilmersdorf | #66 Katholische Kirchengemeinde Maria unter dem Kreuz | register_id | same hard id BE_ZUWDB:kör_100050 as #66 (deterministic hard-id merge) |
| #68 Katholische Kirchengemeinde Pfarrei Bernhard Lichtenberg Berlin-Mitte, Gemeinde Herz Jesu | #67 Katholische Kirchengemeinde Pfarrei Bernhard Lichtenberg Berlin-Mitte | register_id | same hard id BE_ZUWDB:kör_100261 as #67 (deterministic hard-id merge) |
| #70 Katholische Pfarrei Bernhard Lichtenberg Berlin-Mitte, Gemeinde Herz Jesu | #67 Katholische Kirchengemeinde Pfarrei Bernhard Lichtenberg Berlin-Mitte | register_id | same hard id BE_ZUWDB:kör_100261 as #67 (deterministic hard-id merge) |
| #75 KLIK - Rechte und Ressourcen für wohnungslose Menschen e. V. | #74 KLIK - Kontakt-, Beratungs- und Koordinierungsarbeit für junge Menschen auf der Straße e. V. | register_id | same hard id BE_ZUWDB:vr_031870 as #74 (deterministic hard-id merge) |
| #83 milaa miteinander leben aber anders | #82 milaa | register_id | same hard id BE_ZUWDB:hrb_169036 as #82 (deterministic hard-id merge) |
| #89 Notdienst für Suchtmittelgefährdete und -abhängige Berlin e. V. | #88 Notdienst Berlin e. V. | register_id | same hard id BE_ZUWDB:vr_007649 as #88 (deterministic hard-id merge) |
| #107 Unionhilfswerk Soziale Dienste gGmbH, WoTa | #106 Unionhilfswerk Soziale Dienste gGmbH | register_id | same hard id BE_ZUWDB:hrb_134136 as #106 (deterministic hard-id merge) |
| #227 PulsM GmbH | #122 PulsM GmbH | manual | Lead review (docs/org_merges.tsv): same name and legal form (GmbH), same seat München in both TED notices; #122 holds USt-IdNr DE275992867, #227's notice printed no Land |
| #120 Living Quarter GmbH | #126 Living Quarter GmbH | manual | Lead review (docs/org_merges.tsv): same name and legal form (GmbH); #126 (USt-IdNr DE302502970) and #189 give seat Berlin, #120 no seat; the differing Land (BE/BB/NI) is TED's place-of-performance NUTS, not the seat |
| #189 Living Quarter GmbH | #126 Living Quarter GmbH | manual | Lead review (docs/org_merges.tsv): same name and legal form (GmbH), seat Berlin in both TED notices; Land NI is TED's place-of-performance NUTS, #126 holds USt-IdNr DE302502970 |
| #226 Jonas Better Place GmbH | #128 Jonas Better Place GmbH | manual | Lead review (docs/org_merges.tsv): same name and legal form (GmbH), same seat München in both TED notices; #128 holds USt-IdNr DE285972251, #226's notice printed no Land |
| #224 Saxonia Catering GmbH &amp; Co.KG | #149 Saxonia-Catering GmbH & Co. KG | ust_id | same hard id UST:DE257193663 as #149 (deterministic hard-id merge) |

