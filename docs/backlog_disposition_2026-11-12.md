# Backlog disposition - 2026-11-12

Every one of the 188 backlog rows from the live sweep is accounted for here.
The sweep (`backlog_full.txt`) requested each listing URL with an impersonated
Chrome client and recorded the HTTP status, page length, count of detail links,
and any framework markers (`NEXT` = `__NEXT_DATA__`, `nextf` = App Router,
`nuxt` = `__NUXT_DATA__`). The measured class below is the reason the row is not
in the matrix.

## Summary

| Disposition | Rows |
|---|---:|
| Built and CI-verified in this pass (or earlier) | 9 |
| Already registered / built earlier | 22 |
| HTTP 403 bot or login wall | 64 |
| DNS / SSL / timeout | 37 |
| HTTP 503 / 523 refuses automated requests | 3 |
| Next.js App Router (unsupported config-only) | 0 |
| Nuxt (unsupported config-only) | 0 |
| Next.js shell, ads client-fetched | 0 |
| HTTP 200, no discoverable detail links | 0 |
| Measured per-site rejection (named reason) | 53 |
| Other measured blocker | 0 |
| **Total** | **188** |

## Full disposition

| # | Domain | Country | Probe | Detail links | Disposition |
|---:|---|---|---|---:|---|
| 1 | staff.am | Armenia | 200 | 4 | staff_am (Armenia) - built and CI-verified 2026-11-12 |
| 2 | zhaopin.com | China | 200 | 237 | zhaopin_com (China) - built and CI-verified 2026-11-12 |
| 3 | jobalert.ie | Ireland | 200 | 0 | jobalert_ie (Ireland) - built and CI-verified 2026-11-12 |
| 4 | doda.jp | Japan | 200 | 192 | doda_jp (Japan) - built and CI-verified 2026-11-12 |
| 5 | emprego.co.mz | Mozambique | 200 | 1 | emprego_co_mz (Mozambique) - built and CI-verified 2026-11-12 |
| 6 | olx.pl | Poland | 200 | 21 | olx_pl (Poland) - built and CI-verified 2026-11-12 |
| 7 | hh.ru | Russia | 200 | 5 | hh_ru (Russia) - built and CI-verified 2026-11-12 |
| 8 | tanitjobs.com | Tunisia | 200 | 80 | tanitjobs (Tunisia) - already built; kept BUILT (Disabled in CI) because the datacenter IP hits a bot challenge |
| 9 | vietnamworks.com | Vietnam | 200 | 8 | vietnamworks_vn (Vietnam) - built and CI-verified 2026-11-12 |
| 10 | rabota.by | Belarus | 200 | 29 | already present in the live matrix (built in an earlier pass) |
| 11 | posao.ba | Bosnia and Herzegovi | 200 | 38 | already present in the live matrix (built in an earlier pass) |
| 12 | multitrabajos.com | Ecuador | 200 | 0 | already present in the live matrix (built in an earlier pass) |
| 13 | tecoloco.com.sv | El Salvador | 200 | 167 | already present in the live matrix (built in an earlier pass) |
| 14 | duunitori.fi | Finland | 403 | 0 | already present in the live matrix (built in an earlier pass) |
| 15 | talent.com | Global | ERR | 0 | already present in the live matrix (built in an earlier pass) |
| 16 | tecoloco.com.gt | Guatemala | 200 | 131 | already present in the live matrix (built in an earlier pass) |
| 17 | tecoloco.com.hn | Honduras | 200 | 98 | already present in the live matrix (built in an earlier pass) |
| 18 | hh.kz | Kazakhstan | 200 | 9 | already present in the live matrix (built in an earlier pass) |
| 19 | jobs.li | Liechtenstein | ERR | 0 | already present in the live matrix (built in an earlier pass) |
| 20 | cvbankas.lt | Lithuania | 200 | 129 | already present in the live matrix (built in an earlier pass) |
| 21 | rabota.md | Moldova | 200 | 21 | already present in the live matrix (built in an earlier pass) |
| 22 | myjobs.com.mm | Myanmar | 200 | 3 | already present in the live matrix (built in an earlier pass) |
| 23 | trademe.co.nz | New Zealand | 200 | 0 | already present in the live matrix (built in an earlier pass) |
| 24 | tecoloco.com.ni | Nicaragua | 200 | 120 | already present in the live matrix (built in an earlier pass) |
| 25 | kariera.mk | North Macedonia | 200 | 7 | already present in the live matrix (built in an earlier pass) |
| 26 | konzerta.com | Panama | 200 | 0 | already present in the live matrix (built in an earlier pass) |
| 27 | mycareersfuture.gov.sg | Singapore | 200 | 0 | already present in the live matrix (built in an earlier pass) |
| 28 | arbetsformedlingen.se | Sweden | 200 | 5 | already present in the live matrix (built in an earlier pass) |
| 29 | jobs.ch | Switzerland | 200 | 29 | already present in the live matrix (built in an earlier pass) |
| 30 | 518.com.tw | Taiwan | 200 | 21 | already present in the live matrix (built in an earlier pass) |
| 31 | hh.uz | Uzbekistan | 200 | 10 | already present in the live matrix (built in an earlier pass) |
| 32 | duapune.com | Albania | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 33 | seek.com.au | Australia | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 34 | boss.az | Azerbaijan | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 35 | emploibenin.com | Benin | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 36 | catho.com.br | Brazil | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 37 | jobs.bg | Bulgaria | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 38 | emploi.cm | Cameroon | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 39 | eluta.ca | Canada | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 40 | jobillico.com | Canada | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 41 | trabajando.cl | Chile | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 42 | emploi.cd | Congo (Democratic Re | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 43 | jobs.cz | Czech Republic | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 44 | profesia.cz | Czech Republic | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 45 | emploi.ci | Côte d'Ivoire | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 46 | wuzzuf.net | Egypt | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 47 | cv.ee | Estonia | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 48 | cvkeskus.ee | Estonia | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 49 | apec.fr | France | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 50 | stellenanzeigen.de | Germany | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 51 | stepstone.de | Germany | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 52 | ghanajob.com | Ghana | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 53 | kariera.gr | Greece | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 54 | irishjobs.ie | Ireland | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 55 | jobs.ie | Ireland | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 56 | alljobs.co.il | Israel | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 57 | drushim.co.il | Israel | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 58 | cv.lv | Latvia | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 59 | cvmarket.lv | Latvia | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 60 | llv.li | Liechtenstein | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 61 | cvmarket.lt | Lithuania | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 62 | jobs.lu | Luxembourg | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 63 | moovijob.com | Luxembourg | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 64 | jobstreet.com.my | Malaysia | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 65 | keepmeposted.com.mt | Malta | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 66 | occ.com.mx | Mexico | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 67 | emploi.ma | Morocco | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 68 | werkzoeken.nl | Netherlands | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 69 | seek.co.nz | New Zealand | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 70 | jobz.pk | Pakistan | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 71 | jobs.ps | Palestine | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 72 | encuentra24.com | Panama | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 73 | jobstreet.com.ph | Philippines | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 74 | pracuj.pl | Poland | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 75 | remote.co | Remote | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 76 | ejobs.ro | Romania | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 77 | avito.ru | Russia | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 78 | rwandajob.com | Rwanda | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 79 | jadarat.sa | Saudi Arabia | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 80 | fastjobs.sg | Singapore | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 81 | jobstreet.com.sg | Singapore | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 82 | pnet.co.za | South Africa | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 83 | milanuncios.com | Spain | 403 | 1 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 84 | jobbsafari.se | Sweden | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 85 | jobscout24.ch | Switzerland | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 86 | zoomtanzania.net | Tanzania | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 87 | th.jobsdb.com | Thailand | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 88 | kariyer.net | Türkiye | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 89 | yenibiris.com | Türkiye | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 90 | dou.ua | Ukraine | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 91 | work.ua | Ukraine | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 92 | cv-library.co.uk | United Kingdom | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 93 | totaljobs.com | United Kingdom | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 94 | snagajob.com | United States | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 95 | buscojobs.com.uy | Uruguay | 403 | 0 | HTTP 403 - bot/login wall on the listing page (impersonation does not clear it) |
| 96 | anem.dz | Algeria | ERR | 0 | unreachable at probe time (DNSError) |
| 97 | empregoangola.com | Angola | ERR | 0 | unreachable at probe time (DNSError) |
| 98 | inefop.gov.ao | Angola | ERR | 0 | unreachable at probe time (Timeout) |
| 99 | emploi.bj | Benin | ERR | 0 | unreachable at probe time (DNSError) |
| 100 | jobs.molhr | Bhutan | ERR | 0 | unreachable at probe time (DNSError) |
| 101 | dpsm.gov.bw | Botswana | ERR | 0 | unreachable at probe time (DNSError) |
| 102 | anpe.bf | Burkina Faso | ERR | 0 | unreachable at probe time (DNSError) |
| 103 | emploi.bf | Burkina Faso | ERR | 0 | unreachable at probe time (DNSError) |
| 104 | nea.gov.kh | Cambodia | ERR | 0 | unreachable at probe time (Timeout) |
| 105 | multiempleos.com | Dominican Republic | ERR | 0 | unreachable at probe time (DNSError) |
| 106 | socioempleo.gob.ec | Ecuador | ERR | 0 | unreachable at probe time (DNSError) |
| 107 | fijitimes.com | Fiji | ERR | 0 | unreachable at probe time (Timeout) |
| 108 | jobnet.ge | Georgia | ERR | 0 | unreachable at probe time (DNSError) |
| 109 | guatejobs.com | Guatemala | ERR | 0 | unreachable at probe time (DNSError) |
| 110 | profession.hu | Hungary | ERR | 0 | unreachable at probe time (Timeout) |
| 111 | job.visir.is | Iceland | ERR | 0 | unreachable at probe time (DNSError) |
| 112 | timesjobs.com | India | ERR | 0 | unreachable at probe time (CertificateVerifyError) |
| 113 | hh.kg | Kyrgyzstan | ERR | 0 | unreachable at probe time (Timeout) |
| 114 | emploi.mg | Madagascar | ERR | 0 | unreachable at probe time (DNSError) |
| 115 | anpe.ml | Mali | ERR | 0 | unreachable at probe time (DNSError) |
| 116 | job.mn | Mongolia | ERR | 0 | unreachable at probe time (CertificateVerifyError) |
| 117 | anapec.ma | Morocco | ERR | 0 | unreachable at probe time (Timeout) |
| 118 | hipo.ro | Romania | ERR | 0 | unreachable at probe time (Timeout) |
| 119 | emploi.sn | Senegal | ERR | 0 | unreachable at probe time (Timeout) |
| 120 | ess.gov.si | Slovenia | ERR | 0 | unreachable at probe time (DNSError) |
| 121 | empleate.gob.es | Spain | ERR | 0 | unreachable at probe time (CertificateVerifyError) |
| 122 | topjobs.lk | Sri Lanka | ERR | 0 | unreachable at probe time (SSLError) |
| 123 | jobb.blocket.se | Sweden | ERR | 0 | unreachable at probe time (DNSError) |
| 124 | job.tj | Tajikistan | ERR | 0 | unreachable at probe time (DNSError) |
| 125 | ajira.go.tz | Tanzania | ERR | 0 | unreachable at probe time (SSLError) |
| 126 | newsday.co.tt | Trinidad and Tobago | ERR | 0 | unreachable at probe time (DNSError) |
| 127 | emploi.nat.tn | Tunisia | ERR | 0 | unreachable at probe time (SSLError) |
| 128 | nafis.gov.ae | United Arab Emirates | ERR | 0 | unreachable at probe time (Timeout) |
| 129 | ish.mehnat.uz | Uzbekistan | ERR | 0 | unreachable at probe time (Timeout) |
| 130 | ulsa.va | Vatican City | ERR | 0 | unreachable at probe time (DNSError) |
| 131 | brightermonday.co.zm | Zambia | ERR | 0 | unreachable at probe time (DNSError) |
| 132 | jobsearch.co.zw | Zimbabwe | ERR | 0 | unreachable at probe time (DNSError) |
| 133 | chakri.com | Bangladesh | 523 | 0 | HTTP 523 - the origin refuses automated requests |
| 134 | anpe.bj | Benin | 503 | 1 | HTTP 503 - the origin refuses automated requests |
| 135 | next.rikunabi.com | Japan | 503 | 1 | HTTP 503 - the origin refuses automated requests |
| 136 | au.jora.com | Australia | 200 | 0 | JS aggregator shell |
| 137 | bdjobs.com | Bangladesh | 200 | 0 | home redirects to /h/ and exposes no ad links; search is JS/POST-driven |
| 138 | jobat.be | Belgium | 200 | 0 | HTTP 403 Cloudflare challenge |
| 139 | vdab.be | Belgium | 200 | 9 | JS shell: no server-rendered ad links |
| 140 | jobsbotswana.com | Botswana | 200 | 0 | 114-byte empty response |
| 141 | bongthom.com | Cambodia | 200 | 0 | classifieds |
| 142 | goodwork.ca | Canada | 200 | 3 | JS shell: no server-rendered ad links |
| 143 | workinnonprofits.ca | Canada | 200 | 0 | listing exposes no ad links on the home page |
| 144 | chiletrabajos.cl | Chile | ERR | 0 | timeout during the live sweep |
| 145 | burzarada.hzz.hr | Croatia | 200 | 4 | detail pages carry no job description body |
| 146 | moj-posao.net | Croatia | 200 | 44 | Nuxt (__NUXT_DATA__); unsupported config-only |
| 147 | revolico.com | Cuba | 200 | 29 | Cuba classifieds; data lives in Apollo __APOLLO_STATE__, and the site is not a job board |
| 148 | jobindex.dk | Denmark | 200 | 2 | listing exposes no ad links; search is JS-driven |
| 149 | tyomarkkinatori.fi | Finland | 200 | 6 | no job-list route on the site (JS portal) |
| 150 | francetravail.fr | France | 200 | 0 | JS shell / requires the gated public API |
| 151 | skywalker.gr | Greece | 200 | 69 | detail pages return HTTP 403 |
| 152 | cvonline.hu | Hungary | 200 | 0 | bot-check interstitial |
| 153 | vinnumalastofnun.is | Iceland | 200 | 3 | Apollo/Next app; /starfatorg is 404 and ads are not discoverable config-only |
| 154 | job.com.bd | India | 200 | 16 | listing exposes only employer/category links, no ad links |
| 155 | infojobs.it | Italy | 200 | 0 | consent/JS interstitial |
| 156 | subito.it | Italy | 200 | 13 | Next.js App Router (self.__next_f); unsupported config-only |
| 157 | work.kz | Kazakhstan | 200 | 0 | tiny JS shell |
| 158 | jobs.kg | Kyrgyzstan | 200 | 0 | Next.js App Router (self.__next_f); unsupported config-only |
| 159 | adem.public.lu | Luxembourg | 200 | 6 | no job-list route on the site (JS public-employment portal) |
| 160 | maukerja.my | Malaysia | 200 | 1 | only 10 featured ads on the home page; no working listing path |
| 161 | jobsplus.gov.mt | Malta | 200 | 6 | JS shell: no server-rendered ad links |
| 162 | lexpress.mu | Mauritius | 200 | 124 | classifieds: detail pages are ad listings, not job postings |
| 163 | zangia.mn | Mongolia | 200 | 0 | Next.js App Router (self.__next_f); unsupported config-only |
| 164 | posao.me | Montenegro | 200 | 0 | tiny JS shell |
| 165 | merojob.com | Nepal | 200 | 9 | Next.js App Router (self.__next_f); unsupported config-only |
| 166 | nationalevacaturebank.nl | Netherlands | 200 | 0 | tiny JS/consent shell |
| 167 | werk.nl | Netherlands | 200 | 0 | JS shell |
| 168 | vrabotuvanje.com.mk | North Macedonia | 200 | 19 | Nuxt (__NUXT_DATA__); unsupported config-only |
| 169 | finn.no | Norway | 200 | 13 | JSON-LD wrapped in a single-key script envelope the framework cannot unwrap |
| 170 | rozee.pk | Pakistan | 200 | 810 | detail pages return HTTP 403 (bot wall) |
| 171 | aptitus.com | Peru | 200 | 0 | redirects cross-brand to bumeran.com.pe (Peru already covered) |
| 172 | emprego.pt | Portugal | 200 | 0 | general job portal landing page; no ad links on the probed URL |
| 173 | mojedelo.com | Slovenia | 200 | 0 | tiny JS shell |
| 174 | jobkorea.co.kr | South Korea | 200 | 24 | Next.js App Router (self.__next_f); unsupported config-only |
| 175 | saramin.co.kr | South Korea | 200 | 86 | listing links go through a login relay page; no anonymous ad HTML |
| 176 | infojobs.net | Spain | 200 | 5 | listing exposes only city/company links; ads are JS-loaded |
| 177 | xpress.jobs | Sri Lanka | 200 | 0 | 1.7 KB JS shell |
| 178 | jobup.ch | Switzerland | 200 | 22 | JS shell: the listing carries no server-rendered ad links |
| 179 | 104.com.tw | Taiwan | 200 | 0 | detail pages bot-blocked (HTTP 403) |
| 180 | 1111.com.tw | Taiwan | 200 | 54 | detail pages bot-blocked (HTTP 403) |
| 181 | landing.jobs | Tech | 200 | 14 | JS shell: no server-rendered ad links |
| 182 | jobbkk.com | Thailand | 200 | 32 | Next.js App Router (self.__next_f); unsupported config-only |
| 183 | ugandajobline.com | Uganda | 200 | 0 | listing exposes no ad links on the home page |
| 184 | robota.ua | Ukraine | 200 | 0 | tiny JS/consent shell |
| 185 | ziprecruiter.com | United States | 200 | 3 | bot-blocked (HTTP 403 / challenge) |
| 186 | gallito.com.uy | Uruguay | 200 | 0 | listing URL returns HTTP 404 |
| 187 | olx.uz | Uzbekistan | 200 | 9 | classifieds; no job-specific detail contract |
| 188 | topcv.vn | Vietnam | 200 | 30 | bot-blocked after an earlier revert |

## Classes in plain text

### Built and CI-verified in this pass (or earlier) (9)

- **staff.am** (Armenia) - staff_am (Armenia) - built and CI-verified 2026-11-12
- **zhaopin.com** (China) - zhaopin_com (China) - built and CI-verified 2026-11-12
- **jobalert.ie** (Ireland) - jobalert_ie (Ireland) - built and CI-verified 2026-11-12
- **doda.jp** (Japan) - doda_jp (Japan) - built and CI-verified 2026-11-12
- **emprego.co.mz** (Mozambique) - emprego_co_mz (Mozambique) - built and CI-verified 2026-11-12
- **olx.pl** (Poland) - olx_pl (Poland) - built and CI-verified 2026-11-12
- **hh.ru** (Russia) - hh_ru (Russia) - built and CI-verified 2026-11-12
- **tanitjobs.com** (Tunisia) - tanitjobs (Tunisia) - already built; kept BUILT (Disabled in CI) because the datacenter IP hits a bot challenge
- **vietnamworks.com** (Vietnam) - vietnamworks_vn (Vietnam) - built and CI-verified 2026-11-12

### Already registered / built earlier (22)

- **rabota.by** (Belarus) - already present in the live matrix (built in an earlier pass)
- **posao.ba** (Bosnia and Herzegovi) - already present in the live matrix (built in an earlier pass)
- **multitrabajos.com** (Ecuador) - already present in the live matrix (built in an earlier pass)
- **tecoloco.com.sv** (El Salvador) - already present in the live matrix (built in an earlier pass)
- **duunitori.fi** (Finland) - already present in the live matrix (built in an earlier pass)
- **talent.com** (Global) - already present in the live matrix (built in an earlier pass)
- **tecoloco.com.gt** (Guatemala) - already present in the live matrix (built in an earlier pass)
- **tecoloco.com.hn** (Honduras) - already present in the live matrix (built in an earlier pass)
- **hh.kz** (Kazakhstan) - already present in the live matrix (built in an earlier pass)
- **jobs.li** (Liechtenstein) - already present in the live matrix (built in an earlier pass)
- **cvbankas.lt** (Lithuania) - already present in the live matrix (built in an earlier pass)
- **rabota.md** (Moldova) - already present in the live matrix (built in an earlier pass)
- **myjobs.com.mm** (Myanmar) - already present in the live matrix (built in an earlier pass)
- **trademe.co.nz** (New Zealand) - already present in the live matrix (built in an earlier pass)
- **tecoloco.com.ni** (Nicaragua) - already present in the live matrix (built in an earlier pass)
- **kariera.mk** (North Macedonia) - already present in the live matrix (built in an earlier pass)
- **konzerta.com** (Panama) - already present in the live matrix (built in an earlier pass)
- **mycareersfuture.gov.sg** (Singapore) - already present in the live matrix (built in an earlier pass)
- **arbetsformedlingen.se** (Sweden) - already present in the live matrix (built in an earlier pass)
- **jobs.ch** (Switzerland) - already present in the live matrix (built in an earlier pass)
- **518.com.tw** (Taiwan) - already present in the live matrix (built in an earlier pass)
- **hh.uz** (Uzbekistan) - already present in the live matrix (built in an earlier pass)

### HTTP 403 bot or login wall (64)

- **duapune.com** (Albania) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **seek.com.au** (Australia) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **boss.az** (Azerbaijan) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **emploibenin.com** (Benin) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **catho.com.br** (Brazil) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobs.bg** (Bulgaria) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **emploi.cm** (Cameroon) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **eluta.ca** (Canada) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobillico.com** (Canada) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **trabajando.cl** (Chile) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **emploi.cd** (Congo (Democratic Re) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobs.cz** (Czech Republic) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **profesia.cz** (Czech Republic) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **emploi.ci** (Côte d'Ivoire) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **wuzzuf.net** (Egypt) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **cv.ee** (Estonia) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **cvkeskus.ee** (Estonia) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **apec.fr** (France) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **stellenanzeigen.de** (Germany) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **stepstone.de** (Germany) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **ghanajob.com** (Ghana) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **kariera.gr** (Greece) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **irishjobs.ie** (Ireland) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobs.ie** (Ireland) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **alljobs.co.il** (Israel) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **drushim.co.il** (Israel) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **cv.lv** (Latvia) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **cvmarket.lv** (Latvia) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **llv.li** (Liechtenstein) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **cvmarket.lt** (Lithuania) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobs.lu** (Luxembourg) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **moovijob.com** (Luxembourg) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobstreet.com.my** (Malaysia) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **keepmeposted.com.mt** (Malta) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **occ.com.mx** (Mexico) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **emploi.ma** (Morocco) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **werkzoeken.nl** (Netherlands) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **seek.co.nz** (New Zealand) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobz.pk** (Pakistan) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobs.ps** (Palestine) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **encuentra24.com** (Panama) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobstreet.com.ph** (Philippines) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **pracuj.pl** (Poland) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **remote.co** (Remote) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **ejobs.ro** (Romania) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **avito.ru** (Russia) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **rwandajob.com** (Rwanda) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jadarat.sa** (Saudi Arabia) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **fastjobs.sg** (Singapore) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobstreet.com.sg** (Singapore) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **pnet.co.za** (South Africa) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **milanuncios.com** (Spain) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobbsafari.se** (Sweden) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **jobscout24.ch** (Switzerland) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **zoomtanzania.net** (Tanzania) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **th.jobsdb.com** (Thailand) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **kariyer.net** (Türkiye) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **yenibiris.com** (Türkiye) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **dou.ua** (Ukraine) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **work.ua** (Ukraine) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **cv-library.co.uk** (United Kingdom) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **totaljobs.com** (United Kingdom) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **snagajob.com** (United States) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)
- **buscojobs.com.uy** (Uruguay) - HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)

### DNS / SSL / timeout (37)

- **anem.dz** (Algeria) - unreachable at probe time (DNSError)
- **empregoangola.com** (Angola) - unreachable at probe time (DNSError)
- **inefop.gov.ao** (Angola) - unreachable at probe time (Timeout)
- **emploi.bj** (Benin) - unreachable at probe time (DNSError)
- **jobs.molhr** (Bhutan) - unreachable at probe time (DNSError)
- **dpsm.gov.bw** (Botswana) - unreachable at probe time (DNSError)
- **anpe.bf** (Burkina Faso) - unreachable at probe time (DNSError)
- **emploi.bf** (Burkina Faso) - unreachable at probe time (DNSError)
- **nea.gov.kh** (Cambodia) - unreachable at probe time (Timeout)
- **multiempleos.com** (Dominican Republic) - unreachable at probe time (DNSError)
- **socioempleo.gob.ec** (Ecuador) - unreachable at probe time (DNSError)
- **fijitimes.com** (Fiji) - unreachable at probe time (Timeout)
- **jobnet.ge** (Georgia) - unreachable at probe time (DNSError)
- **guatejobs.com** (Guatemala) - unreachable at probe time (DNSError)
- **profession.hu** (Hungary) - unreachable at probe time (Timeout)
- **job.visir.is** (Iceland) - unreachable at probe time (DNSError)
- **timesjobs.com** (India) - unreachable at probe time (CertificateVerifyError)
- **hh.kg** (Kyrgyzstan) - unreachable at probe time (Timeout)
- **emploi.mg** (Madagascar) - unreachable at probe time (DNSError)
- **anpe.ml** (Mali) - unreachable at probe time (DNSError)
- **job.mn** (Mongolia) - unreachable at probe time (CertificateVerifyError)
- **anapec.ma** (Morocco) - unreachable at probe time (Timeout)
- **hipo.ro** (Romania) - unreachable at probe time (Timeout)
- **emploi.sn** (Senegal) - unreachable at probe time (Timeout)
- **ess.gov.si** (Slovenia) - unreachable at probe time (DNSError)
- **empleate.gob.es** (Spain) - unreachable at probe time (CertificateVerifyError)
- **topjobs.lk** (Sri Lanka) - unreachable at probe time (SSLError)
- **jobb.blocket.se** (Sweden) - unreachable at probe time (DNSError)
- **job.tj** (Tajikistan) - unreachable at probe time (DNSError)
- **ajira.go.tz** (Tanzania) - unreachable at probe time (SSLError)
- **newsday.co.tt** (Trinidad and Tobago) - unreachable at probe time (DNSError)
- **emploi.nat.tn** (Tunisia) - unreachable at probe time (SSLError)
- **nafis.gov.ae** (United Arab Emirates) - unreachable at probe time (Timeout)
- **ish.mehnat.uz** (Uzbekistan) - unreachable at probe time (Timeout)
- **ulsa.va** (Vatican City) - unreachable at probe time (DNSError)
- **brightermonday.co.zm** (Zambia) - unreachable at probe time (DNSError)
- **jobsearch.co.zw** (Zimbabwe) - unreachable at probe time (DNSError)

### HTTP 503 / 523 refuses automated requests (3)

- **chakri.com** (Bangladesh) - HTTP 523 - the origin refuses automated requests
- **anpe.bj** (Benin) - HTTP 503 - the origin refuses automated requests
- **next.rikunabi.com** (Japan) - HTTP 503 - the origin refuses automated requests

### Measured per-site rejection (named reason) (53)

- **au.jora.com** (Australia) - JS aggregator shell
- **bdjobs.com** (Bangladesh) - home redirects to /h/ and exposes no ad links; search is JS/POST-driven
- **jobat.be** (Belgium) - HTTP 403 Cloudflare challenge
- **vdab.be** (Belgium) - JS shell: no server-rendered ad links
- **jobsbotswana.com** (Botswana) - 114-byte empty response
- **bongthom.com** (Cambodia) - classifieds
- **goodwork.ca** (Canada) - JS shell: no server-rendered ad links
- **workinnonprofits.ca** (Canada) - listing exposes no ad links on the home page
- **chiletrabajos.cl** (Chile) - timeout during the live sweep
- **burzarada.hzz.hr** (Croatia) - detail pages carry no job description body
- **moj-posao.net** (Croatia) - Nuxt (__NUXT_DATA__); unsupported config-only
- **revolico.com** (Cuba) - Cuba classifieds; data lives in Apollo __APOLLO_STATE__, and the site is not a job board
- **jobindex.dk** (Denmark) - listing exposes no ad links; search is JS-driven
- **tyomarkkinatori.fi** (Finland) - no job-list route on the site (JS portal)
- **francetravail.fr** (France) - JS shell / requires the gated public API
- **skywalker.gr** (Greece) - detail pages return HTTP 403
- **cvonline.hu** (Hungary) - bot-check interstitial
- **vinnumalastofnun.is** (Iceland) - Apollo/Next app; /starfatorg is 404 and ads are not discoverable config-only
- **job.com.bd** (India) - listing exposes only employer/category links, no ad links
- **infojobs.it** (Italy) - consent/JS interstitial
- **subito.it** (Italy) - Next.js App Router (self.__next_f); unsupported config-only
- **work.kz** (Kazakhstan) - tiny JS shell
- **jobs.kg** (Kyrgyzstan) - Next.js App Router (self.__next_f); unsupported config-only
- **adem.public.lu** (Luxembourg) - no job-list route on the site (JS public-employment portal)
- **maukerja.my** (Malaysia) - only 10 featured ads on the home page; no working listing path
- **jobsplus.gov.mt** (Malta) - JS shell: no server-rendered ad links
- **lexpress.mu** (Mauritius) - classifieds: detail pages are ad listings, not job postings
- **zangia.mn** (Mongolia) - Next.js App Router (self.__next_f); unsupported config-only
- **posao.me** (Montenegro) - tiny JS shell
- **merojob.com** (Nepal) - Next.js App Router (self.__next_f); unsupported config-only
- **nationalevacaturebank.nl** (Netherlands) - tiny JS/consent shell
- **werk.nl** (Netherlands) - JS shell
- **vrabotuvanje.com.mk** (North Macedonia) - Nuxt (__NUXT_DATA__); unsupported config-only
- **finn.no** (Norway) - JSON-LD wrapped in a single-key script envelope the framework cannot unwrap
- **rozee.pk** (Pakistan) - detail pages return HTTP 403 (bot wall)
- **aptitus.com** (Peru) - redirects cross-brand to bumeran.com.pe (Peru already covered)
- **emprego.pt** (Portugal) - general job portal landing page; no ad links on the probed URL
- **mojedelo.com** (Slovenia) - tiny JS shell
- **jobkorea.co.kr** (South Korea) - Next.js App Router (self.__next_f); unsupported config-only
- **saramin.co.kr** (South Korea) - listing links go through a login relay page; no anonymous ad HTML
- **infojobs.net** (Spain) - listing exposes only city/company links; ads are JS-loaded
- **xpress.jobs** (Sri Lanka) - 1.7 KB JS shell
- **jobup.ch** (Switzerland) - JS shell: the listing carries no server-rendered ad links
- **104.com.tw** (Taiwan) - detail pages bot-blocked (HTTP 403)
- **1111.com.tw** (Taiwan) - detail pages bot-blocked (HTTP 403)
- **landing.jobs** (Tech) - JS shell: no server-rendered ad links
- **jobbkk.com** (Thailand) - Next.js App Router (self.__next_f); unsupported config-only
- **ugandajobline.com** (Uganda) - listing exposes no ad links on the home page
- **robota.ua** (Ukraine) - tiny JS/consent shell
- **ziprecruiter.com** (United States) - bot-blocked (HTTP 403 / challenge)
- **gallito.com.uy** (Uruguay) - listing URL returns HTTP 404
- **olx.uz** (Uzbekistan) - classifieds; no job-specific detail contract
- **topcv.vn** (Vietnam) - bot-blocked after an earlier revert
