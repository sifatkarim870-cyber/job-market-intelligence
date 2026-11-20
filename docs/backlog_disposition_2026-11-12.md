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
| Built and CI-verified in this pass (or earlier) | 13 |
| Already registered / built earlier | 22 |
| HTTP 403 bot or login wall | 63 |
| DNS / SSL / timeout | 37 |
| HTTP 503 / 523 refuses automated requests | 3 |
| Next.js App Router (unsupported config-only) | 0 |
| Nuxt (unsupported config-only) | 0 |
| Next.js shell, ads client-fetched | 0 |
| HTTP 200, no discoverable detail links | 0 |
| Measured per-site rejection (named reason) | 50 |
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
| 125 | ajira.go.tz | Tanzania | BUILT | 16 | portal.ajira.go.tz has active public GraphQL endpoint (/candidates/graphql); built as ajira_tz API scraper 2026-11-15 |
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
| 142 | goodwork.ca | Canada | BUILT | 46 | server-rendered directory /jobs + structured section postings; built as goodwork_ca API scraper 2026-11-15 |
| 143 | workinnonprofits.ca | Canada | 200 | 50 | workinnonprofits_ca (Canada) - built and CI-verified 2026-11-15 |
| 144 | chiletrabajos.cl | Chile | ERR | 0 | timeout during the live sweep |
| 145 | burzarada.hzz.hr | Croatia | 200 | 4 | detail pages carry no job description body |
| 146 | moj-posao.net | Croatia | BUILT | 100 | server-rendered search pagination + Nuxt 3 state deserializer; built as mojposao_hr API scraper 2026-11-15 |
| 147 | revolico.com | Cuba | 200 | 29 | Cuba classifieds; data lives in Apollo __APOLLO_STATE__, and the site is not a job board |
| 148 | jobindex.dk | Denmark | 200 | 2 | listing exposes no ad links; search is JS-driven |
| 149 | tyomarkkinatori.fi | Finland | 200 | 6 | no job-list route on the site (JS portal) |
| 150 | francetravail.fr | France | 200 | 0 | JS shell / requires the gated public API |
| 151 | skywalker.gr | Greece | 200 | 69 | detail pages return HTTP 403 |
| 152 | cvonline.hu | Hungary | 200 | 0 | bot-check interstitial |
| 153 | vinnumalastofnun.is | Iceland | 200 | 3 | Apollo/Next app; /starfatorg is 404 and ads are not discoverable config-only |
| 154 | job.com.bd | Bangladesh | BUILT | 60 | server-rendered search pagination /jobs?page={page} + clean semantic sections; built as job_com_bd API scraper 2026-11-16; kept BUILT (Disabled in CI) because origin drops Azure datacenter IPs |
| 155 | infojobs.it | Italy | 200 | 0 | consent/JS interstitial |
| 156 | subito.it | Italy | 200 | 13 | Next.js App Router (self.__next_f); unsupported config-only |
| 157 | work.kz | Kazakhstan | 200 | 0 | tiny JS shell |
| 158 | jobs.kg | Kyrgyzstan | 200 | 0 | Next.js App Router (self.__next_f); unsupported config-only |
| 159 | adem.public.lu | Luxembourg | 200 | 6 | adem_lu (Luxembourg) - built as dedicated API scraper 2026-11-15; CI run 43629165500 verified green (60 inserted, 0 failed) |
| 160 | maukerja.my | Malaysia | 200 | 1 | only 10 featured ads on the home page; no working listing path |
| 161 | jobsplus.gov.mt | Malta | 200 | 6 | JS shell: no server-rendered ad links |
| 162 | lexpress.mu | Mauritius | 200 | 124 | classifieds: detail pages are ad listings, not job postings |
| 163 | zangia.mn | Mongolia | 200 | 0 | Next.js App Router (self.__next_f); unsupported config-only |
| 164 | posao.me | Montenegro | 200 | 0 | tiny JS shell |
| 165 | merojob.com | Nepal | BUILT | 182 | public REST API endpoints at api.merojob.com/api/v1/jobs/ and /api/v1/jobs/{id}/; built as merojob_np API scraper 2026-11-15 |
| 166 | nationalevacaturebank.nl | Netherlands | 200 | 0 | tiny JS/consent shell |
| 167 | werk.nl | Netherlands | 200 | 0 | JS shell |
| 168 | vrabotuvanje.com.mk | North Macedonia | BUILT | 68 | homepage + /rabotni-mesta directory + Nuxt 3 state deserializer; built as vrabotuvanje_mk API scraper 2026-11-15 |
| 169 | finn.no | Norway | BUILT | 51 | server-rendered search pagination + JobPosting JSON-LD under script:ld+json; built as finn_no API scraper 2026-11-15 |
| 170 | rozee.pk | Pakistan | 200 | 810 | rozee_pk (Pakistan) - built via the browser framework 2026-11-13; plain HTTP 403s but the rendered detail page publishes full JobPosting JSON-LD |
| 171 | aptitus.com | Peru | 200 | 0 | redirects cross-brand to bumeran.com.pe (Peru already covered) |
| 172 | emprego.pt | Portugal | 200 | 0 | general job portal landing page; no ad links on the probed URL |
| 173 | mojedelo.com | Slovenia | 200 | 0 | mojedelo (Slovenia) - built via the browser framework 2026-11-13; the listing is JS-rendered but each detail page publishes full JobPosting JSON-LD (its passive reCAPTCHA badge needed a config-gated ignore) |
| 174 | jobkorea.co.kr | South Korea | 200 | 115 | jobkorea_kr (South Korea) - BUILT 2026-11-16; paginates server-rendered search directory at /recruit/joblist?Page={page}&menucode=local&localorder=1, extracting Schema.org JobPosting JSON-LD and detail sections; CI verified (run 43773212988: 50 inserted, 0 failed, exported to HF) |
| 175 | saramin.co.kr | South Korea | 200 | 86 | listing links go through a login relay page; no anonymous ad HTML |
| 176 | infojobs.net | Spain | 200 | 5 | listing exposes only city/company links; ads are JS-loaded |
| 177 | xpress.jobs | Sri Lanka | 200 | 0 | 1.7 KB JS shell |
| 178 | jobup.ch | Switzerland | 200 | 22 | JS shell: the listing carries no server-rendered ad links |
| 179 | 104.com.tw | Taiwan | 200 | 20 | 104_tw (Taiwan) - built via the browser framework 2026-11-14; plain HTTP 403s on Cloudflare but SeleniumBase UC mode renders search & detail with full JobPosting JSON-LD |
| 180 | 1111.com.tw | Taiwan | 200 | 33 | 1111_tw (Taiwan) - built via browser framework; runs locally (33 ads/page), kept BUILT (Disabled in CI) because runner datacenter IP hits persistent captcha_ch wall |
| 181 | landing.jobs | Tech | 200 | 14 | landing_jobs (Portugal) - built via the browser framework 2026-11-13; disabled in CI (runner datacenter IP served a Cloudflare challenge) |
| 182 | jobbkk.com | Thailand | BUILT | 25 | server-rendered pagination /jobs/lists/{page} + JobPosting JSON-LD; built as jobbkk_th API scraper 2026-11-15 |
| 183 | ugandajobline.com | Uganda | 200 | 0 | listing exposes no ad links on the home page |
| 184 | robota.ua | Ukraine | 200 | 0 | tiny JS/consent shell |
| 185 | ziprecruiter.com | United States | 200 | 3 | bot-blocked (HTTP 403 / challenge) |
| 186 | gallito.com.uy | Uruguay | 200 | 20 | BUILT as gallito_uy (trabajo.gallito.com.uy subdomain, plain HTTP, Schema.org JSON-LD) |
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
- **ajira.go.tz** (Tanzania) - RESOLVED 2026-11-15: SSLError was due to apex domain; portal at portal.ajira.go.tz provides public GraphQL endpoint /candidates/graphql with queries getVacancies and getVacancy(vacancyId). Built as ajira_tz API scraper.
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

### Measured per-site rejection (named reason) (51)

- **au.jora.com** (Australia) - JS aggregator shell
- **bdjobs.com** (Bangladesh) - home redirects to /h/ and exposes no ad links; search is JS/POST-driven
- **jobat.be** (Belgium) - HTTP 403 Cloudflare challenge
- **vdab.be** (Belgium) - JS shell: no server-rendered ad links
- **jobsbotswana.com** (Botswana) - 114-byte empty response
- **bongthom.com** (Cambodia) - classifieds
- **goodwork.ca** (Canada) - RESOLVED 2026-11-15: server-rendered directory /jobs + structured section postings mapped; built as goodwork_ca API scraper.
- **workinnonprofits.ca** (Canada) - RESOLVED 2026-11-15: public XML feed /dynamic/job_feed_rss2.xml + central_content detail parser mapped; built as workinnonprofits_ca API scraper.
- **chiletrabajos.cl** (Chile) - timeout during the live sweep
- **burzarada.hzz.hr** (Croatia) - detail pages carry no job description body
- **moj-posao.net** (Croatia) - RESOLVED 2026-11-15: Nuxt 3 __NUXT_DATA__ state deserializer implemented; built as mojposao_hr API scraper.
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
- **adem.public.lu** (Luxembourg) - built as dedicated API scraper 2026-11-15 (`adem_lu`); CTIE JobBoard REST endpoint streams NDJSON feed with >2,600 live vacancies; CI run 43629165500 verified green (60 inserted, 0 failed, Parquet shard exported). LIVE in scheduled CI matrix.
- **maukerja.my** (Malaysia) - only 10 featured ads on the home page; no working listing path
- **jobsplus.gov.mt** (Malta) - JS shell: no server-rendered ad links
- **lexpress.mu** (Mauritius) - classifieds: detail pages are ad listings, not job postings
- **zangia.mn** (Mongolia) - Next.js App Router (self.__next_f); unsupported config-only
- **posao.me** (Montenegro) - tiny JS shell
- **merojob.com** (Nepal) - RESOLVED 2026-11-15: public REST API endpoints at api.merojob.com/api/v1/jobs/ and /api/v1/jobs/{id}/ mapped; built as merojob_np API scraper.
- **nationalevacaturebank.nl** (Netherlands) - tiny JS/consent shell
- **werk.nl** (Netherlands) - JS shell
- **vrabotuvanje.com.mk** (North Macedonia) - RESOLVED 2026-11-15: Nuxt 3 __NUXT_DATA__ state deserializer implemented; built as vrabotuvanje_mk API scraper.
- **finn.no** (Norway) - RESOLVED 2026-11-15: JSON-LD wrapped under script:ld+json unwrapped and mapped; built as finn_no API scraper.
- **rozee.pk** (Pakistan) - built via the browser framework 2026-11-13 (`rozee_pk`); plain HTTP 403s but the rendered detail page publishes full JobPosting JSON-LD
- **aptitus.com** (Peru) - redirects cross-brand to bumeran.com.pe (Peru already covered)
- **emprego.pt** (Portugal) - general job portal landing page; no ad links on the probed URL
- **mojedelo.com** (Slovenia) - built via the browser framework 2026-11-13 (`mojedelo`); the listing renders client-side but every ad publishes full JobPosting JSON-LD, and its passive reCAPTCHA badge is declared inert with the new config-gated `ignore_challenge_markers`; verified in CI (run 43324675623)
- **jobkorea.co.kr** (South Korea) - built 2026-11-16 (`jobkorea_kr`); paginates server-rendered search directory at `/recruit/joblist?Page={page}&menucode=local&localorder=1` (115+ vacancies per page), extracting structured Schema.org `JobPosting` JSON-LD and detail sections with KRW salaries; verified in CI (run 43773212988: 50 inserted, 0 failed, Parquet shard exported to HF)
- **saramin.co.kr** (South Korea) - listing links go through a login relay page; no anonymous ad HTML
- **infojobs.net** (Spain) - listing exposes only city/company links; ads are JS-loaded
- **xpress.jobs** (Sri Lanka) - 1.7 KB JS shell
- **jobup.ch** (Switzerland) - JS shell: the listing carries no server-rendered ad links
- **104.com.tw** (Taiwan) - built via the browser framework 2026-11-14 (`104_tw`); plain HTTP 403s on Cloudflare but SeleniumBase UC mode renders search & detail with full JobPosting JSON-LD
- **1111.com.tw** (Taiwan) - built via browser framework (`1111_tw`); runs locally (33 ads/page), kept BUILT (Disabled in CI) because runner datacenter IP hits persistent captcha_ch wall
- **landing.jobs** (Tech) - built via the browser framework 2026-11-13 (`landing_jobs`); the listing at `https://landing.jobs/jobs` renders 50 ads whose detail pages publish full JobPosting JSON-LD, but CI runs 43311284418/43311901554 were served a Cloudflare challenge from the runner's datacenter IP, so it is kept BUILT (Disabled in CI)
- **jobbkk.com** (Thailand) - RESOLVED 2026-11-15: server-rendered search pagination + JobPosting JSON-LD mapped; built as jobbkk_th API scraper.
- **ugandajobline.com** (Uganda) - listing exposes no ad links on the home page
- **robota.ua** (Ukraine) - tiny JS/consent shell
- **ziprecruiter.com** (United States) - bot-blocked (HTTP 403 / challenge)
- **gallito.com.uy** (Uruguay) - BUILT as `gallito_uy`; subdomain trabajo.gallito.com.uy serves plain HTTP with Schema.org JSON-LD. CI run 43924056179: 50 inserted, exported to HF. LIVE.
- **olx.uz** (Uzbekistan) - classifieds; no job-specific detail contract
- **topcv.vn** (Vietnam) - bot-blocked after an earlier revert
- **jobnet.com.mm** (Myanmar) - RESOLVED 2026-11-20: server-rendered listing pagination + Schema.org `JobPosting` JSON-LD mapped; built as `jobnet_mm` API scraper. `json.loads(strict=False)` required for tab chars in Description; non-ASCII URL paths percent-encoded. CI run 44611231120: 30 inserted, 0 failed, exported to HF. LIVE in scheduled CI matrix.
- **emploi.ci** (C�te d'Ivoire) - RESOLVED 2026-11-20: server-rendered listing pagination + Schema.org `JobPosting` JSON-LD mapped; built as `emploi_ci` API scraper. Regex repair for unescaped description quotes in JSON-LD; XOF currency mapped (0.0016 USD). CI run 44613872590: 50 inserted, 0 failed, exported to HF. LIVE in scheduled CI matrix.
- **topjobs.lk** (Sri Lanka) - RESOLVED 2026-11-20: the 2026-10-04 probe recorded an SSLError and reached nothing, but the site now serves HTTP 200 to plain requests. Server-rendered JSP listing at `/applicant/vacancybyfunctionalarea.jsp?jst=OPEN&pageNo={page}` (4,583 unique open job codes across 6 pages); rows are `onclick=createAlert(...)` popups rather than anchors, and the ad page carries the body plus the ad-status labels. Built as the `topjobs_lk` HTML scraper; Sri Lanka's first `ref.countries` row (LK) and the LKR currency were part of the work. Most ads are image-only (239 of 250 in the CI run), stored with a NULL description and `description_is_image=true`. CI run 44623966782: 250 inserted, 0 failed, exported to HF. LIVE in scheduled CI matrix.
- **emploi.cd** (DR Congo) - RESOLVED 2026-11-20: the 2026-10-04 probe recorded HTTP 403 behind a Cloudflare challenge and reached nothing, but the site now serves HTTP 200 to plain requests with no challenge. Server-rendered search directory at /recherche-jobs-congo-rdc?page={page} holds the whole board (90 offers over 4 pages, 89 unique ad URLs; the page after the last one returns 200 with zero links). Every ad embeds Schema.org JobPosting JSON-LD, but some descriptions carry unescaped inline-HTML quotes, repaired the same way emploi_ci does. Built as the `emploi_cd` API scraper; DR Congo's first ref.countries row (CD) and the CDF currency were part of the work. employmentType is often the multi-value 'CDI - CDD - Interim - Freelance', stored as NULL rather than one guess; no ad published a salary, so salary_disclosed is false and CDF/monthly states the market. CI run 44632202307: 89 inserted, 0 failed, exported to HF. LIVE in scheduled CI matrix.
- **emploibenin.com** (Benin) - RESOLVED 2026-11-20: the 2026-10-04 probe recorded HTTP 403 behind a Cloudflare challenge and reached nothing, but the site now serves HTTP 200 to plain requests with no challenge; robots.txt (HTTP 200) allows '/' and asks for Crawl-delay: 10. The server-rendered search directory at /recherche-jobs-benin?page={page} holds the whole board (209 offers over 9 pages, no overlap; the page after the last one returns 200 with zero links). Every ad embeds Schema.org JobPosting JSON-LD, but addressRegion is a city list rather than a region (dropped from the stored location) and some descriptions carry unescaped inline-HTML quotes, repaired the same way emploi_ci/emploi_cd do. employmentType is often multi-value ('Freelance - Temps partiel', 'CDI - Freelance'), stored as NULL rather than one guess. Built as the `emploibenin_com` API scraper; Benin's first ref.countries row (BJ) and 25 Benin cities were part of the work, plus Poitiers (FR) because the board also advertises on-site roles in France. No ad published a salary, so salary_disclosed is false and XOF/monthly states the market. CI run 44662056423: 120 inserted, 0 failed, exported to HF. LIVE in scheduled CI matrix.
- **emploi.cm** (Cameroon) - RESOLVED 2026-11-20: the 2026-10-04 probe recorded HTTP 403 behind a Cloudflare challenge and reached nothing, but the site now serves HTTP 200 to plain requests with no challenge; robots.txt (HTTP 200) allows the search and ad paths and asks for Crawl-delay: 10. The server-rendered search directory at /recherche-jobs-cameroun?page={page} holds the whole board (418 unique offers over 17 pages, 419 links with one URL repeating; the page after the last one returns 200 with zero links). Every ad embeds Schema.org JobPosting JSON-LD, but addressCountry is the French label 'Cameroun', addressRegion is a city list rather than a region (dropped from the stored location), some addressLocality values are the same city list or just 'Cameroun' (also dropped), and some descriptions carry unescaped inline-HTML quotes, repaired the same way emploi_ci/emploi_cd do. employmentType is often multi-value ('CDI - CDD - Interim - Freelance'), stored as NULL rather than one guess. Built as the `emploi_cm` API scraper; Cameroon's first ref.countries row (CM) and 25 Cameroon cities were part of the work, plus Djibouti (DJ) because one measured on-site expatriation ad names Djibouti while the board still labels the country 'Cameroun'. No ad published a salary, so salary_disclosed is false and XAF/monthly states the market. CI run 44670844960: 120 inserted, 0 failed, exported to HF. LIVE in scheduled CI matrix.
- **emploi.ma** (Morocco) - BUILT 2026-11-20 as `emploi_ma` via the browser framework: the whole domain is behind a Cloudflare managed challenge (plain requests and curl_cffi get HTTP 403 on every path) and a real browser clears it from a residential IP. Discovery is the search directory `/recherche-jobs-maroc?page={page}` (25 ads per page, pager through page 26); every ad embeds a Schema.org JobPosting with an HTML description. Locally 20/20 ads parsed with bodies and employers, all 20 rows resolved to MA, and 30 Moroccan cities were seeded (which also gives rekrute_com real cities). DISABLED IN CI: run 44683774390 was served the same 'Just a moment...' challenge from the runner's datacenter IP (the listing never exposed its ad links within 60 s, 0 records), so it is kept BUILT (Disabled in CI) and runs locally until the block lifts.
- **emploi.mg** (Madagascar) - NOT BUILDABLE 2026-11-20: the domain does not resolve. `Resolve-DnsName` returns no records for either emploi.mg or www.emploi.mg, and requests fails with NameResolutionError over both http and https, so there is no HTTP response of any kind to scrape; the 2026-10-04 URLError was the same NXDOMAIN, not a transient timeout. Re-probed DNS on 2026-11-20 with the same result. Nothing can be fixed at the scraper layer; Madagascar stays uncovered until a live Malagasy board is identified (the workbook's other candidate, 'Madajob', still lists no domain).
- **emploi.nat.tn** (Tunisia) - NOT BUILDABLE 2026-11-20: DNS resolves (www -> CNAME -> 197.11.97.4) and TCP connects, but the host closes before any HTTP response. requests and curl_cffi raise SSLError 'Connection closed abruptly' on https and ConnectionError 'Empty reply from server' on http; curl.exe fails the TLS handshake at 1.0/1.2/1.3 with any SNI; a real Chrome shows ERR_CONNECTION_CLOSED. The 2026-10-04 ConnectionResetError was the same condition. The address is in Tunisia's public-sector range, so this is a national-IP restriction or an origin outage, not a scraper problem. Tunisia stays covered by keejob_tn (60 rows) and tanitjobs (built, disabled).
- **emploi.sn** (Senegal) - NOT BUILDABLE 2026-11-20: DNS resolves (emploi.sn and www -> 160.0.176.72, delegated to ns.gouv.sn) but TCP to :443 and :80 times out after 20-30 s with requests, curl.exe and a real browser (ERR_TUNNEL_CONNECTION_FAILED). The 2026-10-04 URLError was the same condition. The address is in Senegal's public-sector range, so this is a national-IP restriction or an origin outage, not a scraper problem; Senegal stays covered by emploidakar_com (built, active).
- **empleate.gob.es** (Spain) - RESOLVED 2026-11-20: the 2026-10-04 probe recorded a CertificateVerifyError and reached nothing, but the host now serves a valid chain to Windows Schannel and HTTP 200 to an OpenSSL client once its omitted intermediate certificate is supplied. The leaf is issued by 'Entrust OV TLS Issuing RSA CA 2' under the Sectigo Public Server Authentication Root R46 that certifi already ships; the handshake omits the intermediate, so requests, curl_cffi and openssl all fail 'unable to get local issuer certificate' while Schannel succeeds only because the OS cached it. The intermediate was fetched from the leaf's own AIA URL, verified with 'openssl verify' -> OK, and shipped with the scraper (appended to a copy of certifi's roots), so certificate verification stays ON. robots.txt allows '/' with no Crawl-delay. Discovery and content are the SAME request: the AngularJS front end reads a public Solr endpoint (open/offersearch/selectBuscador) that returns the whole posting inside the listing document - 26,073 visible ads, rows capped at 100 server-side, sort mandatory and 'fechaCreacion desc, id desc' for stable page boundaries, so one request per 100 ads needs no per-ad detail stage. Built as the `empleate_es` API scraper; Andorra's `ref.countries` row (AD) and 52 Spanish provinces in `ref.regions` were seeded as part of the work. CI run 44718454947: 1,000 inserted, 0 failed, exported to HF. LIVE in scheduled CI matrix.
- **chiletrabajos.cl** (Chile) - RESOLVED 2026-11-20: the 2026-10-04 sweep recorded only "timeout during the live sweep", but the domain resolves worldwide (US/Canada/Brazil/Germany probes get HTTP 200 from the same address) and was unreachable only from the Bangladesh build network. The advertised sitemap (/sitemap.xml) is a single <urlset> of /trabajo/<slug>-<id> URLs in newest-first order - 34,473 entries on 2026-11-20 - and every ad page carries a Schema.org `JobPosting` JSON-LD block. Built as the `chiletrabajos_cl` API scraper; Chile's 16 regions (region_code CL-XX), 58 comunas in ref.cities and SOURCE_HOME_COUNTRY["chiletrabajos_cl"]="CL" were seeded as part of the work. CI run 44725446124: 500 fetched, 500 inserted, 0 failed; all 500 rows resolved to CL/Chile (0 NULL country, 0 global-remote fallback), 126 with a disclosed CLP/monthly salary, exported to HF. LIVE in the scheduled CI matrix.
- **cv-library.co.uk** (United Kingdom) - NOT BUILDABLE 2026-11-20: the site is fronted by a Cloudflare hard-deny ("CV-Library.co.uk - Blocked / You triggered a security action", `server: cloudflare`, `__cf_bm` cookie, echoing the client IP and country), not a solvable challenge, so there is no browser trick around it. Measured from two independent egresses. From this build network, plain requests, curl_cffi (chrome124/chrome120/safari17_0) and a real Chrome via SeleniumBase UC all get HTTP 403 on /robots.txt, /sitemap.xml, /jobs, /search-jobs?q=..., /job/<id>/<slug>, /rss and /jobs-rss. From a US datacenter fetch service only the cached homepage returns 200 (602,430 bytes: a Next.js shell, no /job/<id> links, and no job API - its only /api/ references are /api/media/file/* static assets) while robots.txt and every dynamic path still return 403. Because robots.txt itself is unreadable, robots compliance cannot be established, so no scraper can be shipped honestly; a residential proxy is prohibited and CV-Library's partner feed needs a key, which is also prohibited. UK coverage therefore stays on reed (built, active, 2,361 rows), with Totaljobs still a browser-only backlog row.
- **catho.com.br** (Brazil) - NOT BUILDABLE 2026-11-20: the 2026-10-04 sweep recorded "HTTP 403 - bot/login wall on the listing page (impersonation does not clear it)", and the deny is broader than that. Every path (/, /robots.txt, /sitemap.xml, /vagas/, /vagas-de-emprego/, /api.) returns a bare AWS ALB fixed-response `403 Forbidden` (server: awselb/2.0, 520-byte static body, no challenge page, no cookie, no redirect) from this build network and from a US datacenter fetch service, and also to a real Chrome via SeleniumBase UC and to Googlebot and bingbot user-agents; curl_cffi impersonation (chrome124/chrome120/safari17_0) changes nothing. Because robots.txt itself is 403, robots compliance cannot be established. The shape of the block (ALB fixed-response, country-agnostic rejection of every non-allowlisted client) means the site is effectively Brazil-IP-only, so a scraper could only run behind a Brazilian proxy, which is prohibited, and Catho's partner feed needs a key, which is also prohibited. Brazil coverage stays on gupy_io and vagas_com_br (both built and active).
- **apec.fr** (France) - NOT BUILDABLE 2026-11-20: the 2026-10-04 sweep recorded "HTTP 403 with anti-bot signals", and the wall is DataDome, not a solvable challenge. Every content path (/, /robots.txt, /sitemap.xml, /candidat/recherche-emploi.html, /candidat/recherche-emploi.html/emploi/detail-offre/<id>, /employeur, /nos-services, /rss/offres.xml) returns a 403 DataDome interstitial (`window.ddjskey`, `geo.captcha-delivery.com`, 767 bytes) from this build network and from a US datacenter fetch service, to plain requests, to curl_cffi impersonation (chrome124/chrome120/safari17_0) and to a real Chrome (SeleniumBase UC). APEC's own JSON API is protected too: POST /cms/webservices/rechercheOffre, GET /cms/webservices/offre/public?idOffre=... and /cms/webservices/offre/public/<id> all return DataDome 403 JSON, and the 404 page shows `ajaxListenerPath: ['/cms/webservices', '/.apec-login.do']`, i.e. the protection is deliberately wired to the API prefix. Only static CMS paths answer, and they carry no postings. Because robots.txt itself is 403, robots compliance cannot be established. A residential French proxy is prohibited and the APEC partner API needs a key, so France stays on hellowork_com (built, active, 1,350 rows).
- **anapec.ma** (Morocco) - NOT BUILDABLE 2026-11-20: DNS resolves (anapec.ma and www -> 196.61.236.125, and anapec.org/www.anapec.org -> 196.61.236.121, both at Maroc Datacenter, NS ns1/ns2.marocdatacenter.ma) but TCP to :443 and :80 times out after 20-30 s with requests and curl.exe from this build network, and a US datacenter fetch service fails the connection too (transport error, no HTTP response). No other host exists: offres/emploi/candidat/eservices/e-services/portail.anapec.ma are all NXDOMAIN. The 2026-10-04 URLError was the same condition. Because the address is in Morocco's national range, this is an IP-geography restriction or an origin outage, not a scraper problem, and it cannot be fixed at the scraper layer (a proxy is prohibited). Morocco stays on rekrute_com (built, active) and emploi_ma (built, disabled in CI).
- **boss.az** (Azerbaijan) - NOT BUILDABLE 2026-11-20: the domain is behind a Cloudflare firewall rule that returns "Sorry, you have been blocked / You are unable to access boss.az" (server: cloudflare, 4,542-byte cf error page, `noindex, nofollow`) - not the "Just a moment..." challenge the 2026-10-04 sweep recorded. It is a hard deny on /, /robots.txt and /vacancies alike, from this build network and from a US datacenter fetch service, to plain requests, to curl_cffi impersonation (chrome124/chrome120/safari17_0) and to a real Chrome (SeleniumBase UC; the rendered page is the same Cloudflare 5xx-error landing). There is no challenge token to solve and no cookie the client can obtain, because the edge refuses before the origin. robots.txt itself is 403, so robots compliance cannot be established. Only a proxy in an allowed geography would reach it, which is prohibited. Azerbaijan stays on jobsearch_az and hellojob (both built and active).
- **maukerja.my** (Malaysia) - RESOLVED 2026-11-20: the 2026-10-04 sweep recorded "only 10 featured ads on the home page; no working listing path", and the listing path (/jobsearch/all-jobs) is indeed Cloudflare-walled (HTTP 403 "Just a moment..."), but the board advertises its own sitemaps: /sitemap.xml -> /mk_job.xml -> /mk_job1.xml is a single <urlset> of 46,652 /job/<id>-<slug> ad URLs in newest-first order (2026-11-20, ~9.0 MB), and every ad page carries a Schema.org JobPosting JSON-LD block (title, employer + logo, description, baseSalary in MYR/month, skills, jobBenefits, dates). Built as the `maukerja_my` API scraper, Malaysia's first built source; 21 extra Malaysian cities in ref.cities and SOURCE_HOME_COUNTRY["maukerja_my"]="MY" were seeded as part of the work. robots.txt bans AI-crawler tokens (none sent) and disallows no path this scraper uses. CI run 44749107293: 500 fetched, 500 inserted, 0 failed; all 500 rows resolved (494 MY, 6 SG), 0 NULL country, 0 global-remote fallback, 437 at city level across 22 cities, 475 with a disclosed MYR/monthly salary, 5 flagged remote from jobLocationType TELECOMMUTE, exported to HF. LIVE in the scheduled CI matrix.
- **jobup.ch** (Switzerland) - RESOLVED 2026-11-20: the 2026-10-04 sweep recorded a JS shell ("the listing carries no server-rendered ad links"). That is true of the listing page, but the board advertises a sitemap index (/sitemaps/jobup/en/sitemap.xml) that leads to /sitemaps/jobup/en/job/sitemap.job-en.xml.gz, a single gzip <urlset> of 30,590 /en/jobs/detail/<uuid>/ ad URLs written oldest-first (the client sorts by lastmod descending so fresh_rows stays true), and every ad page carries a Schema.org JobPosting JSON-LD block. robots.txt (HTTP 200) allows the paths this scraper uses. Built as the `jobup_ch` API scraper - JobCloud AG's French-Swiss brand, a distinct inventory from jobs_ch (8 of 15 sampled jobup.ch ad UUIDs 404 on every en/fr/de jobs.ch detail path). Mapping traps: employmentType is a list of Schema.org codes OR prose, and a two-code list or prose like "Permanent position" is stored as no type rather than one guess; baseSalary is a CHF MonetaryAmount whose QuantitativeValue minValue/maxValue are YEAR unitText, and an EMPTY QuantitativeValue is undisclosed, not zero francs; addressLocality is often empty and addressRegion often holds a town instead of a canton, so a non-canton region is reused as the locality (a seeded town then matches a city, a real canton stays a region); applicantLocationRequirements is a Country eligibility statement, NOT a remote signal - only jobLocationType TELECOMMUTE sets remote. Scope added: the 26 Swiss cantons (region_code CH-XX) and 99 Swiss cities in ref.cities, SOURCE_HOME_COUNTRY["jobup_ch"]="CH", and CHF in the USD reference-rate table (jobup.ch is the first CHF source). CI run 44761231830: 30,590 sitemap entries, 500 selected, 497 fetched (3 fetch failures), 497 parsed/inserted, 0 persist failures; all 497 rows resolved to CH (0 NULL country, 0 global-remote fallback), 270 at city level, 132 with a disclosed CHF/yearly salary normalised to USD, exported to HF. LIVE in the scheduled CI matrix.
- **jobscout24.ch** (Switzerland) - NOT BUILDABLE 2026-11-20: the 2026-10-04 sweep recorded "HTTP 403 - bot/login wall on the listing page", and the wall is a CloudFront hard deny rather than a solvable challenge. Every path probed (/, /en/, /robots.txt, /sitemap.xml) returns a fixed "Request blocked" page with server: CloudFront and x-cache: Error from cloudfront from this build network and from a US datacenter fetch service, to plain requests, to curl_cffi impersonation (chrome124/chrome120/safari17_0) and to a real Chrome, and identically to Googlebot and bingbot user-agents. The brand's API hosts are not a route either: api.jobscout24.ch, jobs.jobscout24.ch and static.jobscout24.ch are all NXDOMAIN. Because robots.txt itself is 403, robots compliance cannot be established, so no scraper can be shipped honestly; a proxy is prohibited. Switzerland stays on jobs_ch (built, active) and jobup_ch (built, active).
- **tyomarkkinatori.fi** (Finland) - NOT BUILDABLE 2026-11-20: the 2026-10-04 sweep recorded "no job-list route on the site (JS portal)", and a deeper probe confirms there is no keyless surface a compliant scraper may use. robots.txt is HTTP 200, and its generic `*` group disallows `/api/` and `/*/api/`; the ONLY machine-readable job data on the site lives under that disallowed `/api/` prefix - the listing widget `/widgets/TmtTyopaikkaHakuV2/index.js` posts to `/api/jobpostingfulltext/search/v2/search` and reads `/api/jobposting-new/v1/public/jobpostings/` and `/api/jobposting/v1` (GET on the search path returns 405, it needs POST). The user-facing surfaces are JS shells: the listing `/henkiloasiakkaat/avoimet-tyopaikat` returns byte-identical ~162 KB markup for every `ae/f/p/ps/q` query string (client-rendered results, 0 anchors to ads, 0 `JobPosting` and 0 `ld+json`), and an ad URL `/henkiloasiakkaat/avoimet-tyopaikat/<uuid>/fi` is a 200 page whose `<title>` is the generic listing title with no JSON-LD either. There is no sitemap: sitemap.xml, sitemap_index.xml and sitemap-index.xml all 404 (the 404 body is the SPA shell served as text/html), and `/henkiloasiakkaat/avoimet-tyopaikat/sitemap.xml` answers 200 with that same SPA HTML rather than an XML `<urlset>`. The officially documented Retrieval Interface (v2.0, `/jobpostingProvider/swagger/api-docs/` and the Instructions-and-support pages) requires a KEHA-issued, business-ID-linked credential, which is prohibited here; the legacy open host `paikat.te-palvelut.fi` is NXDOMAIN and there is no `avoindata.tyomarkkinatori.fi`. Under the project's own policy (RFC 9309 against the generic `*` group; `docs/source_expansion_plan.md`) a readable `Disallow` is binding - distinct from the unreadable-robots case, which is unknown, not permitted. A proxy is prohibited. Finland stays on duunitori_fi (built, active); tyopaikat_oikotie_fi is disabled (portal permanently closed).
