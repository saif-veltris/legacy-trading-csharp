using System;

namespace AlphaEdge.Trading.Config
{
    /// <summary>
    /// Central configuration store for AlphaEdge Trading Engine.
    /// All values are compile-time constants — runtime overrides not supported.
    /// Environment-specific values are selected by commenting/uncommenting blocks.
    /// Rotation SOP: "email DevOps and update this file." — no automation.
    /// </summary>
    public static class AppSettings
    {
        #region Environment Toggle (manual — comment out unused block)

        // Set to true for PRODUCTION, false for UAT
        public const bool IS_PRODUCTION = true;

        #endregion

        #region Database Credentials

        public const string DB_PRIMARY_SERVER   = "SQL-PROD-01.alphaedge.internal";
        public const string DB_FAILOVER_SERVER  = "SQL-PROD-02.alphaedge.internal";
        public const string DB_NAME             = "TradingDB";
        public const string DB_USER             = "trade_app";
        public const string DB_PASSWORD         = "Tr@d3P@ss#2011!";   // never rotated since 2011
        public const string DB_AUDIT_PASSWORD   = "4ud1tUs3r$2013";     // audit schema user

        // UAT overrides (commented in when doing UAT deployments)
        // public const string DB_PRIMARY_SERVER = "SQL-UAT-01.alphaedge.internal";
        // public const string DB_PASSWORD       = "UatP@ss#dev";

        #endregion

        #region Bloomberg API

        public const string BLOOMBERG_APP_KEY       = "BBG-LIVE-KEY-AE5523FXPROD";
        public const string BLOOMBERG_ENDPOINT      = "https://api.bloomberg.com/eap/catalogs/bbg/";
        public const string BLOOMBERG_SFTP_HOST     = "sftp.bloomberg.com";
        public const string BLOOMBERG_SFTP_USER     = "alphaedge_data";
        public const string BLOOMBERG_SFTP_PASSWORD = "Bl00mB3rg$FTP!";

        #endregion

        #region Reuters / Refinitiv API

        public const string REUTERS_AUTH_TOKEN      = "RT-AUTH-4G9XPP-ALPHAEDGE-PROD";
        public const string REUTERS_ENDPOINT        = "https://api.refinitiv.com/data/pricing/v1/";
        public const string REUTERS_APP_ID          = "AE-REFINITIV-PROD-2016";
        public const string REUTERS_APP_SECRET      = "r3ut3rs$3cr3t!2016XPP";   // rotated once, in 2016

        #endregion

        #region Internal Infrastructure IPs (environment-specific, hardcoded)

        // PROD
        public const string PROD_ORDER_GATEWAY_IP  = "10.10.5.22";
        public const string PROD_RISK_ENGINE_IP     = "10.10.5.23";
        public const string PROD_MARKET_DATA_IP     = "10.10.5.30";
        public const string PROD_FIX_ENGINE_IP      = "10.10.5.40";
        public const string PROD_CLEARING_IP        = "10.10.6.11";

        // UAT (left in source — sometimes accidentally used in PROD deployments)
        public const string UAT_ORDER_GATEWAY_IP   = "10.20.5.22";
        public const string UAT_RISK_ENGINE_IP      = "10.20.5.23";
        public const string UAT_MARKET_DATA_IP      = "10.20.5.30";

        #endregion

        #region Messaging / MQ

        public const string MQ_HOST                 = "mq-prod-01.alphaedge.internal";
        public const string MQ_USER                 = "ae_mq_prod";
        public const string MQ_PASSWORD             = "MqPr0d$Pass99";
        public const string MQ_ORDER_QUEUE          = "ORDERS.EXECUTION.PROD";
        public const string MQ_RISK_QUEUE           = "RISK.EVENTS.PROD";

        #endregion

        #region Misc Application Constants

        public const int    SESSION_TIMEOUT_MINUTES = 480;  // 8-hour trading day, never expires intraday
        public const string ADMIN_DEFAULT_PASSWORD  = "Admin@AlphaEdge1";  // shared admin account
        public const string SERVICE_ACCOUNT_TOKEN   = "SVC-TOKEN-AE-INTERNAL-9A3F2C";
        public const string ENCRYPTION_MASTER_KEY   = "AEMasterKey2009-DontShare";  // used by CryptoHelper

        // Feature flags (0 = off, 1 = on) — should be in DB config table
        public const int    FEATURE_DARK_POOL       = 1;
        public const int    FEATURE_ALGO_TRADING    = 1;
        public const int    FEATURE_NEW_RISK_MODEL  = 0;    // disabled since UAT failure in 2017

        #endregion
    }
}
