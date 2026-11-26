# 机构授权与中文文献分支 — 完整协议 (Institutional & CNKI full protocol)

> 本文件由 `download-paper` 主 SKILL.md 的第 8 步进入,是从原 `nature-downloader` 技能完整吸收的机构授权下载协议。
> 进入本分支时必须通读本文件。资产来源:`scripts/`(batch_download.mjs 等 + lib/)、`src/`、`data/`、`examples/`、`tests/`,许可证见 `LICENSE-nature-downloader`。

## 0. 分支路由决策树

```text
规范化 DOI/题名,识别语言、出版商
├─ 中文文献(中文题名 / zh 元数据 / cnki.net 链接 / 用户指明知网)
│  └─ 一律走 CNKI 路线(即使存在其他 OA 副本)—— 见第 5 节
└─ 英文文献
   ├─ 出版商官方版可拿(OA 直链 / 浏览器战术)→ 主 SKILL.md 路线,不走本分支
   ├─ Elsevier / Springer Nature / IEEE,且已配置有效出版商 API Key
   │  ├─ 优先出版商 API 下载(成功即结束,不强制判 OA)
   │  └─ API 失败 → 自动查合法 OA(主 SKILL.md 路线)→ 都失败 → 询问后走 Web Access
   ├─ 有 OA/PMC/预印本副本 → 主 SKILL.md 路线(优先级高于机构权限)
   └─ 无任何免费副本
      ├─ 用户机构图书馆有订阅权限 → Web Access 机构路线 —— 见第 6 节
      └─ 机构无权限/不可用 → 科研通互助(主 SKILL.md step 3b)
```

**批量下载(2 篇以上)默认走 `scripts/batch_download.mjs`**(第 2 节),它自动完成 OA 解析、出版商 API、CNKI、Web Access 的路由;单篇诊断才手工驱动浏览器。

## 1. 资产清单(已并入本技能)

| 路径 | 作用 |
|---|---|
| `scripts/batch_download.mjs` | 批量编排入口:OA / 出版商 API / CNKI / Web Access 全路由,写 manifest |
| `scripts/configure_school.py` | 机构库配置(从用户实际使用的资源门户 URL 推断授权路线),依赖 `src/` |
| `scripts/configure_credentials.py` | 出版商 API 密钥管理(Elsevier / Springer Nature / IEEE) |
| `scripts/browser_pdf_downloader.mjs` | 从浏览器上下文抓 PDF 字节(shell curl 403 但浏览器能开时的标准解法) |
| `scripts/cdp_open_url.mjs` | CDP 代理打开 URL(处理带 `#` 片段的 URL) |
| `scripts/extract_pdf_text.py` | PDF 文本抽取验证 |
| `scripts/retry_elsevier_api.mjs` | Elsevier API 重试辅助 |
| `scripts/lib/anti-bot.mjs` | 自动验证模块:滑块(含 CNKI Geetest)、ScienceDirect 机器人检查、Cloudflare Turnstile、reCAPTCHA 复选框 |
| `scripts/lib/` 其余模块 | 元数据、OA 解析、CNKI、路由、manifest、WoS SI 等支撑逻辑 |
| `data/publishers.json`, `data/schools.yaml`, `data/school.schema.json` | 出版商注册表与学校配置数据(`lib/provider-registry.mjs` 以 `../../data/publishers.json` 相对引用,勿改变目录层级) |
| `examples/*.tsv` | `carsi_retry.tsv` / `publisher_verification.tsv` / `manifest` 模板 |
| `tests/` | 单元测试(`node --test tests/unit/`、`python3 -m pytest tests/python/`) |

运行要求:Node.js 22+、Python 3。配置文件位置(自动读取):
- 机构配置:`~/.config/lit-dl/school.json`(测试可用 `LIT_DL_CONFIG_DIR` 隔离)
- 出版商密钥:`~/.config/lit-dl/credentials.json`(权限 0600)

## 2. 批量下载 batch_download.mjs

**SI 约定(合并后默认值)**:本技能默认连附件一起下,所以批量运行**默认传 `--si`**;仅当用户明说"只要正文"才传 `--no-si`。脚本要求二者必传其一,否则返回 `si_confirmation_required` 且不建输出目录。

```bash
# 主题检索(Web of Science 收录集,取 N 条):
node scripts/batch_download.mjs --topic "rice blast resistance gene" --count 10 --si --out "<project>"
# 显式 DOI 列表:
node scripts/batch_download.mjs --dois "10.1007/s00122-021-03957-1,10.1111/pbi.14066" --si --out "<project>"
# 精确英文题名走 OA(无 DOI 论文的 arXiv 兜底):
node scripts/batch_download.mjs --title "Attention Is All You Need" --open-access --si --out "<project>"
# 中文精确题名(默认 CNKI 路线):
node scripts/batch_download.mjs --title "乡村振兴背景下数字治理研究" --si --out "<project>"
# 中文题名 + 只要 PDF 版:
node scripts/batch_download.mjs --title "..." --cnki-format pdf --si --out "<project>"
# 已知合法 PDF 直链:
node scripts/batch_download.mjs --pdf-url "https://arxiv.org/pdf/1706.03762" --title "Attention Is All You Need" --si --out "<project>"
```

输出 `{ summary, manifest, results }`;PDF 入 `PDFs/`,原生 HTML/XML 入 `FullText/`,CAJ 入 `CNKI/`,补充材料入 `suppl/`(与单篇目录的 `suppl/` 约定一致;代码入 `code/`)。manifest 记录路线、OA 证据、accessMode、格式、MIME、字节数、SHA-256、SI 选择与类型化失败状态;疑似敏感字段递归清除。

**Token 纪律**:绝不要把整页 DOM、检索结果或 PDF/SI 字节 eval 回对话上下文,大数据留在脚本内,只回传紧凑状态。交互式 eval 仅用于单篇路线或诊断一篇卡住的论文。

## 3. 机构库配置(仅 CNKI / Web Access 路线需要)

每次部署或机构档案变化时确认一次:向用户要他**平时实际使用**的图书馆电子资源/数据库平台链接(资源门户、数据库列表、WoS 入口、某数据库详情页、统一身份认证登录链接均可),不要按学校名猜预设。

```bash
python3 scripts/configure_school.py infer "https://example.edu/library/resources"
python3 scripts/configure_school.py url "https://example.edu/library/resources"
python3 scripts/configure_school.py show
python3 scripts/configure_school.py health --force
```

`discovery.web_of_science_url` 存在时作为 WoS 入口,否则回落 `https://www.webofscience.com/wos/woscc/basic-search`;`discovery.cnki_url` 存在时作为 CNKI 入口,否则回落 `https://kns.cnki.net/kns8s/defaultresult/index`。

### 资源 URL 分诊

```text
cas.* / /authserver/login        CAS / SSO 登录页;解析 service= 回调后回到资源门户
idp/shibboleth / carsi           CARSI / Shibboleth 机构联邦路线
ezproxy / libproxy               EZproxy 远程代理
webvpn / vpn                     WebVPN 路线
metaersp / metaauth / uas        图书馆资源聚合门户
webofscience / sciencedirect     数据库/出版商入口;确认是否经门户到达
```

登录页带 `service=` 参数时,把回调主机当作资源服务,登录页本身不是全部工作流。以下均为**登录阶段**而非最终失败:配置的机构登录、联邦、代理、数据库登录主机。以用户地址栏实际出现为准确认机构专属域名(图书馆聚合、发现/库入口、统一身份 SSO、联邦 WAYF、代理/WebVPN)。

## 4. 出版商 API 凭据(Elsevier / Springer Nature / IEEE)

懒配置:只有路线需要时才配置。

```bash
python3 scripts/configure_credentials.py set elsevier
python3 scripts/configure_credentials.py set springer_nature
python3 scripts/configure_credentials.py set ieee --fulltext-endpoint 'https://issued-endpoint.example/articles/{doi}'
python3 scripts/configure_credentials.py show
python3 scripts/configure_credentials.py validate <provider>
python3 scripts/configure_credentials.py delete <provider>
python3 scripts/configure_credentials.py contact-email researcher@example.org
```

官方注册:Elsevier `https://dev.elsevier.com/`;Springer Nature `https://dev.springer.nature.com/docs/quick-start/api-access/`;IEEE `https://developer.ieee.org/member/register`。

**规则**:
- 不主动请用户把 API key 粘贴到对话。若用户**自愿**发送,即视为授权保存该确切密钥:不拒绝、不要求重生成、不复述;经 `configure_credentials.py set <provider> --stdin` 保存,不进命令行参数、日志、回复与 manifest;只报告掩码确认与校验状态。
- IEEE Metadata API ≠ 付费全文;必须拿到签发的 Full-Text Access endpoint 模板才算可经 API 下载。
- 有效 Key 不保证有全文权限(entitlement)。API 返回无权限/无可用全文 → 自动转合法 OA(主 SKILL.md 路线);**API 与 OA 双失败后**,返回 `api_fallback_confirmation_required`,询问一次用户是否改走 Web Access,不自动切换。

## 5. 中文文献 CNKI 路线

**中文文献只走 CNKI**:中文题名、`zh` 元数据、显式 CNKI 链接或 `--route cnki`,即使别处存在 OA 副本也走 CNKI。复用用户当前 Chrome 的图书馆/CNKI 登录态,优先用配置的 `discovery.cnki_url`。**绝不导出 Cookie、绝不收集机构密码。**

- 批量路线:`--title "<中文题名>"`;需要 PDF 版时加 `--cnki-format pdf`(默认可能是 CAJ)。
- **格式原则**:PDF、HTML 全文、CAJ 是不同的交付物。用户要 PDF 时必须有真实 PDF 链接或 `%PDF` 响应;没有就如实报告 `no_authorized_pdf_found` / `pdf_fetch_failed`。**不得把 CAJ、HTML 或登录页当作 PDF 保存。**
- 遇到拼图滑块(含 CNKI Geetest):先用 `scripts/lib/anti-bot.mjs` 自动尝试,估算可见行程距离做渐变拖动,同一标签页最多两次;通过后确认挑战消失并继续用同一标签页。失败即交回用户,保留受挑战的标签页。
- 不做无限量下载:只处理用户确认的明确清单,保持对提供方友好的节奏,留清晰审计记录。

## 6. 英文收费文献:Web Access 机构路线

**适用条件**:英文出版商不属于"配置了 API 的 Elsevier/SN/IEEE",OA 检查不可用;或 API+OA 双失败且用户同意走 Web Access。**前提**是用户机构图书馆对该文献有订阅权限。

### 启动条件(逐项确认)

1. 持有用户图书馆/数据库登录态的浏览器在用户机器上开着;
2. `python3 scripts/configure_school.py show` 配置存在且有效(缺失则先做第 3 节配置);
3. 用户已在**同一浏览器**里登录其机构/图书馆路线;
4. 浏览器控制路径复用同一登录档案。CDP 若附着到陈旧浏览器、临时档案或另一个浏览器,改用能复用用户活跃会话的控制通道,**不要把失败误判为"图书馆无权限"**;
5. Node 22+ / Python 3 可用;
6. web-access CDP 代理可用或可启动:`~/.agents/skills/web-access-main/scripts/check-deps.mjs`(Claude Code 环境为 `~/.claude/skills/web-access-main/scripts/check-deps.mjs`),测试 `curl -sS --max-time 10 http://127.0.0.1:3456/targets`;
7. 用户已认可目标输出目录。

### WoS 工作流

WoS 渲染在 **shadow DOM + 虚拟列表**中,手工抓取必须穿透 shadow root 并滚动加载(batch 脚本已内置)。

1. 经图书馆聚合/机构入口打开 WoS 完成一次认证(用用户平常的路线:机构登录、Shibboleth/OpenAthens/CARSI、CAS/SSO、IP 登录);
2. 确认在已认证的检索页(可见机构名、检索框);
3. 有 DOI 按 **DOI** 检索,否则**精确题名**;读结果页选匹配记录(题名+年份+作者);
4. 打开记录并读取;
5. 依次优先点全文入口:`Free Full Text` / `Open Access` → 图书馆解析链接(`Find it at`、`SFX`、`OpenURL`、`Full Text Links`、`查看全文`、Ovid 等库名)→ 出版商全文(`View Full Text`、出版商名、`View PDF`)。全文链接继承机构会话,通常无需二次登录;出现二次机构接力则按第 7 节完成一次;
6. 出版商页面找 PDF 链接(`PDF`、`View PDF`、`Download PDF`、`pdfft`、`/doi/pdf/`),用 `scripts/browser_pdf_downloader.mjs` 保存:
   ```bash
   node scripts/browser_pdf_downloader.mjs \
     --url "<pdf-url>" --out "<path>.pdf" \
     [--target <targetId>] [--proxy http://127.0.0.1:3456] [--close]
   ```
   该脚本在页面上下文执行 `fetch(location.href, {credentials:"include"})`,分块经本地 CDP 代理传出写盘,默认校验 `%PDF` 签名(`--allow-non-pdf` 用于非 PDF 交付物);
7. 解析器只给可读 HTML 全文而无有效 PDF 链接时:保存 HTML/文本,标记 `full_text_html_available`,明确告知"已获取 HTML 全文,但当前授权路径没有可下载 PDF",不得把 HTML 冒充 PDF;
8. 解析器/提供商明确表示机构无权限:标记 `library_no_permission`,明确告知"当前图书馆资源没有该文献全文权限",不要当作临时网络问题重试出版商直达;
9. SI 默认随正文下载(第 2 节);WoS + `--si` 保持每篇一个可读题名目录、只放已验证主 PDF 与明确标注的 SI、附件落地页最多深入一层、排除 GitHub/Zenodo/Figshare/Dryad/OSF 等外部仓库链接、部分失败记 `partial`;
10. 把走过的路线(WoS → SFX/全文提供商 → 出版商/数据库)记入 manifest。

WoS 无记录或记录无可用全文链接 → `no_full_text_link`;解析器明确拒绝 → `library_no_permission`。

## 7. 浏览器会话、验证与机构登录接力

**浏览器会话原则**:授权下载依赖用户已登录的确切浏览器档案。代理/CDP/自动化工具若打开无登录态的新档案或另一个浏览器,失败不代表图书馆无权限——换能复用用户活跃会话的控制通道,或请用户在受控浏览器实例里完成认证。

**验证优先原则**:用户已认证的 Chrome 会话里出现可见滑块、复选框、机器人检查等简单验证时,先在浏览器内自动尝试(同一标签页最多两次),确认挑战消失后从同一标签页继续。两类情况立即交回用户:有界尝试失败;或需要秘密/身份输入(图形选择、扫码、短信/OTP、passkey、硬件密钥、双因素)。保留受挑战标签页,永不要求用户把凭据或验证码粘贴进对话。

**机构登录接力**(CAS/SSO、CARSI/Shibboleth、OpenAthens、EZproxy、WebVPN、IP 授权):
1. 到达机构登录页/联邦选择页/数据库登录页时停止自动操作;
2. 记入 `carsi_retry.tsv`(表头 `id project title doi year venue publisher failure_stage status source_url current_url next_action`),状态 `carsi_waiting_user`;
3. 明确告知用户哪个标签页需要处理:"页面在你的机构/数据库登录处。若浏览器已自动填好凭据且你授权,我可以点一次可见的登录/确认按钮;否则请在浏览器中完成。"联邦/WAYF 选机构:用户授权且机构无歧义时可代选;
4. 不读取、不存储、不索要密码、扫码结果、OTP、短信码、CAPTCHA、cookie、local/session storage;
5. **安全自动确认五条件**(全部满足才可点一次可见登录/确认/继续按钮,如 `登录`、`确认登录`、`Continue`、`Sign in`):页面在预期的机构/图书馆/联邦/数据库域;用户在本次对话中明确授权;可见动作是明确的登录/确认/继续按钮;无扫码-only、无 OTP、无推送审批、无密码重置、无新数据共享同意、无账户安全警告(滑块与简单机器人检查属可自动尝试项);不读取、不复制、不输入、不修改任何凭据;
6. 登录完成后在同一标签页刷新继续,重新检测页面形态;成功则下载验证并更新 manifest 为 `downloaded` / `downloaded_with_si`;完成后又循环回同一登录页则记 `failed_after_retry` 并附观察原因。

**出版商验证**(ScienceDirect "Are you a robot?"、Cloudflare、Turnstile 等):
- 保守访问模式:优先图书馆聚合/CARSI 入口而非直连 `doi.org`;敏感出版商一次一篇;manifest 留审计;每页等稳定后再找 PDF;复用同一标签页;默认一次尝试,同一标签页最多两次后交回用户;
- 自动验证先试 `scripts/lib/anti-bot.mjs`(简单点击、ScienceDirect 机器人检查、Cloudflare Turnstile、滑块、reCAPTCHA 复选框);成功记 `verification_auto_passed` 继续;失败记 `verification_auto_failed`(用户交接,非终态)交回用户,用户完成后从同一标签页继续一次;挑战立即复现则 `do_not_auto_retry` 并继续下一篇;
- 中断批次时写 `publisher_verification.tsv`(表头 `id project title doi year venue publisher status source_url current_url next_action`)。

## 8. 状态码与审计

每篇文献归入且仅归入一个状态并保持进 manifest:

```text
downloaded / downloaded_with_si / open_access_downloaded / full_text_html_available /
available_not_downloaded / native_fulltext_downloaded / si_confirmation_required /
credentials_missing / credentials_invalid / api_not_entitled / api_fulltext_unavailable /
api_fallback_confirmation_required / oa_not_found / oa_resolution_inconclusive /
metadata_ambiguous / carsi_waiting_user / carsi_resolved_retry_needed /
publisher_verification_waiting_user / sciencedirect_robot_check / retry_after_user_verification /
verification_auto_passed / verification_auto_failed / do_not_auto_retry / url_needs_repair /
library_no_permission / no_full_text_link / publisher_blocked_waiting_user /
no_authorized_pdf_found / failed_after_retry
```

语义要点:
- API-first 下载成功记 `oa_status: not_checked_api_first`(有意跳过 OA 解析,不代表非 OA);`api_fallback_confirmation_required` 仅用于"受支持出版商 API 尝试 + 自动 OA 兜底双双失败"之后;
- `verification_auto_passed` / `verification_auto_failed`:自动验证的成败;后者是用户交接态,不是终态;
- `carsi_waiting_user` 仅当浏览器明显停在机构 SSO/CAS/CARSI/Shibboleth/OpenAthens/数据库认证页;
- `full_text_html_available` 是成功的全文访问结果而非 PDF 下载,须明确告知用户无 PDF;
- `library_no_permission` 是明确的无权限结论,如实告知,不重试直达出版商。

## 9. 边界

- 只用用户合法的机构访问。**不绕过付费墙、DRM、双因素认证。**
- 不要求用户把机构密码、数据库密码、OTP、恢复码、会话令牌粘贴进对话或终端;用户主动提供身份类秘密时婉拒并改用浏览器登录接力(出版商 API key 按第 4 节"收到即保存"规则单独处理)。
- 不检查、不导出 cookie、密码、localStorage、浏览器档案、会话文件;只使用浏览器已认证的页面上下文。
- 不做无界/无差别下载:不把宽泛关键词检索变成无限自动下载,不下整期/整卷/大结果集;每批次保持对提供方友好的节奏。
- 已保存登录页的例外:用户明确说浏览器已自动填好凭据并授权点击可见登录/确认按钮时,可在预期的机构 SSO/CAS/CARSI/Shibboleth 页面点一次该按钮,不读取、不复制、不输入任何凭据。此例外不适用于 CAPTCHA、扫码、短信/OTP、出版商机器人检查、同意/安全警告或预期登录流程之外的任何页面。
- 会话过期:请用户经机构/图书馆路线在同一浏览器重新认证,再重开出版商/数据库入口。