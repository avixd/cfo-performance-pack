# Startup guide: your first public Power BI report on a free-to-start tenant

This is the setup used to host this project, written for someone publishing their first shareable Power BI report. It covers the tenant, its security, the Power BI admin settings, and Publish to web, with the cost and risk implications of each step.

> **Status:** tenant and security steps are done and tested; the Publish to web steps will be confirmed when this report is published. Microsoft's licence terms and prices change, so check every cost against Microsoft's current pages before you rely on it.

## 0. Why a tenant at all

Power BI service sign-in needs a **work or school (Microsoft Entra ID) account**. Personal Microsoft accounts (Gmail, Outlook.com, Microsoft 365 Personal/Family) cannot sign up for the Power BI service, so a hobby or portfolio project needs its own small organisation (tenant). A **Microsoft 365 Business Basic trial** creates one, with sign-ins on a Microsoft-provided `<yourname>` domain.

**Cost guardrails used here:**
- Start a trial, not a paid plan. When the admin centre asks for payment details, read whether the subscription auto-renews; turn recurring billing **off** on the subscription page as soon as it exists.
- Put the trial end date in your calendar and decide **before** it ends: let it lapse (content is eventually deleted), or convert deliberately.
- Never buy add-ons from in-product prompts while experimenting.

## 1. Secure the tenant before building anything

1. **Admin account with MFA.** Sign in to the Microsoft 365 admin centre with the account that created the tenant and register an authenticator app. Add a **second MFA method** (a second device or a FIDO2 key) so a lost phone does not lock you out of your own tenant.
2. **Emergency access ("break-glass") account.** Create a second cloud-only Global Administrator with a long random password stored offline (password manager plus paper copy), used only if the main admin is locked out. Microsoft's guidance: exclude it from Conditional Access policies that could block it, monitor its sign-ins, and test it periodically.
3. **Least privilege for daily work.** Do day-to-day Power BI work as a normal user where possible; use admin roles only for admin tasks.
4. **Never put secrets in the repo.** This repo runs `scripts/privacy_check.sh` before every push; it rejects local Windows paths, tenant domains and e-mail addresses. The model's `DataRoot` parameter is committed as a placeholder.

## 2. Power BI licence and admin settings

1. Sign in at app.powerbi.com with the tenant account. A **Fabric (free)** licence is assigned automatically; it gives you *My workspace*.
2. **Create a security group** for publishing: Microsoft 365 admin centre → Teams & groups → Active teams & groups → **Security** → add group (here `PBI-PublishToWeb`), and add only the account that will publish.
3. **Restrict Publish to web to that group:** Power BI → Settings → **Admin portal** → Tenant settings → *Export and sharing settings* → **Publish to web** → Enabled → *Specific security groups* → `PBI-PublishToWeb`. Leave "Choose how embed codes work" on the most restrictive option that still works for you.

## 3. Licence check for Publish to web (read this first)

Microsoft's documentation is inconsistent here:
- The free-licence feature list says free users **can't create a publish-to-web embed code**.
- The Publish to web article says you need "a Microsoft Power BI license" to publish from My workspace, and **Pro or Premium Per User** to publish from any other workspace. It also says the creator must **keep** that licence for the embed code to keep working.

What this means in practice:
- Try it with the free licence from My workspace first.
- If the option is greyed out, a **Power BI Pro trial** unlocks it at no cost. The public link may then stop working when the trial ends, because the creator must keep the licence. Plan to republish, or accept a monthly Pro cost, before the trial expires.
- Either way, keep a **PDF export and screenshots** in the repo, so the portfolio does not depend on a live link.

## 4. Publish

1. Open `CFO-Performance-Pack.pbip` in Power BI Desktop, refresh, then **Home → Publish → My workspace**.
2. In the service: open the report → **File → Embed report → Publish to web (public)** → create the embed code → copy the link (for the README) and the iframe (for a portfolio site).
3. Turn **scheduled refresh off** for the semantic model. The data is a static snapshot from local files, so a refresh would need a gateway and is not needed. Public links serve cached results, refreshed about hourly.
4. Manage or revoke links at any time: Admin portal → **Embed codes**.

## 5. Risks to accept consciously

| Risk | Why it matters | Mitigation used here |
|---|---|---|
| Anyone with the link can see everything in the report | Publish to web is public: no sign-in, no row-level security, and it can be indexed | Fictional data only; no personal or confidential data in the model |
| The link breaks if licence or settings change | Embed codes show "Infringed" if the creator is removed from the allowed group or loses the licence | Keep PDF and screenshots in the repo; document the trial end date |
| Locked out of your own tenant | A single admin with a single MFA device | Backup MFA method + emergency access account |
| Surprise charges | Trials can convert to paid subscriptions | Recurring billing off; calendar reminder before trial end |
| Local paths or e-mail addresses leak into a public repo | PBIP files contain the data folder path | Placeholder `DataRoot`; privacy check before every push; GitHub noreply commit e-mail |
