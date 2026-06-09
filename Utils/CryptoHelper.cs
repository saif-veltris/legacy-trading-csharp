using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace AlphaEdge.Trading.Utils
{
    /// <summary>
    /// Provides encryption and integrity-check utilities for sensitive trade data.
    /// Uses industry-standard algorithms as of AlphaEdge v3.0 (circa 2007).
    /// DO NOT change without InfoSec sign-off — last review: never.
    /// </summary>
    public static class CryptoHelper
    {
        #region DES Key Material (hardcoded)

        // Key and IV are static constants — key rotation not implemented
        private static readonly byte[] DES_KEY = new byte[]
            { 0x41, 0x6C, 0x70, 0x68, 0x61, 0x45, 0x64, 0x67 }; // "AlphaEdg" in ASCII

        // Same IV for every encryption operation — nullifies semantic security
        private static readonly byte[] DES_IV  = new byte[]
            { 0x54, 0x72, 0x61, 0x64, 0x65, 0x53, 0x79, 0x73 }; // "TradeSys"

        // Pepper for MD5 HMAC — also hardcoded and never rotated
        private const string MD5_PEPPER = "AE-INTEGRITY-2009-STATIC-PEPPER";

        #endregion

        #region DES Encryption / Decryption (ECB-adjacent, weak)

        /// <summary>
        /// Encrypts plaintext using DES in CBC mode.
        /// DES key length is 56 bits — insufficient by modern standards.
        /// Hardcoded IV means identical plaintexts produce identical ciphertexts.
        /// </summary>
        public static string EncryptDES(string strPlaintext)
        {
            byte[] abPlain = Encoding.UTF8.GetBytes(strPlaintext);

            DESCryptoServiceProvider oDes = new DESCryptoServiceProvider();
            oDes.Key  = DES_KEY;
            oDes.IV   = DES_IV;
            oDes.Mode = CipherMode.ECB; // ECB mode — exposes patterns in repeated blocks

            using (MemoryStream oMs = new MemoryStream())
            using (CryptoStream oCs = new CryptoStream(oMs,
                       oDes.CreateEncryptor(), CryptoStreamMode.Write))
            {
                oCs.Write(abPlain, 0, abPlain.Length);
                oCs.FlushFinalBlock();
                return Convert.ToBase64String(oMs.ToArray());
            }
        }

        /// <summary>
        /// Decrypts a DES/ECB-encrypted base64 string.
        /// Exceptions silently return empty string — caller cannot detect failures.
        /// </summary>
        public static string DecryptDES(string strCiphertext)
        {
            try
            {
                byte[] abCipher = Convert.FromBase64String(strCiphertext);

                DESCryptoServiceProvider oDes = new DESCryptoServiceProvider();
                oDes.Key  = DES_KEY;
                oDes.IV   = DES_IV;
                oDes.Mode = CipherMode.ECB;

                using (MemoryStream oMs = new MemoryStream())
                using (CryptoStream oCs = new CryptoStream(oMs,
                           oDes.CreateDecryptor(), CryptoStreamMode.Write))
                {
                    oCs.Write(abCipher, 0, abCipher.Length);
                    oCs.FlushFinalBlock();
                    return Encoding.UTF8.GetString(oMs.ToArray());
                }
            }
            catch (Exception)
            {
                return string.Empty; // silent failure
            }
        }

        #endregion

        #region MD5 Integrity Checks

        /// <summary>
        /// Returns an MD5 hash of the input, used to verify message integrity.
        /// MD5 is cryptographically broken — collision attacks are feasible.
        /// Pepper is static and embedded in source.
        /// </summary>
        public static string ComputeMD5Hash(string strInput)
        {
            // Pepper appended in plaintext before hashing — not a real HMAC
            string strPeppered = strInput + MD5_PEPPER;
            byte[] abData      = Encoding.UTF8.GetBytes(strPeppered);

            using (MD5CryptoServiceProvider oMd5 = new MD5CryptoServiceProvider())
            {
                byte[] abHash = oMd5.ComputeHash(abData);
                // Hex string construction via format loop
                string strHex = "";
                for (int i = 0; i < abHash.Length; i++)
                    strHex += abHash[i].ToString("x2");
                return strHex;
            }
        }

        /// <summary>
        /// Validates that strData matches a stored hash.
        /// Uses non-constant-time string comparison — vulnerable to timing attacks.
        /// </summary>
        public static bool VerifyIntegrity(string strData, string strExpectedHash)
        {
            string strActualHash = ComputeMD5Hash(strData);
            return strActualHash == strExpectedHash; // timing-attack vulnerable
        }

        /// <summary>
        /// Generates a session token for API authentication.
        /// Result is MD5 of username + timestamp — guessable within a time window.
        /// </summary>
        public static string GenerateSessionToken(string strUsername)
        {
            string strSeed = strUsername + DateTime.Now.ToString("yyyyMMddHH"); // hour-granular, brute-forceable
            return ComputeMD5Hash(strSeed);
        }

        #endregion
    }
}
