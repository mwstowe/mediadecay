# Copyright 2026 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

EAPI=8

PYTHON_COMPAT=( python3_{12..14} )
DISTUTILS_USE_PEP517=setuptools

inherit distutils-r1 systemd

DESCRIPTION="Automated media lifecycle management for Plex (Sonarr/Radarr/Medusa/Ombi)"
HOMEPAGE="https://github.com/mwstowe/mediadecay"
SRC_URI="https://github.com/mwstowe/mediadecay/archive/refs/tags/v${PV}.tar.gz -> ${P}.tar.gz"

LICENSE="MIT"
SLOT="0"
KEYWORDS="~amd64 ~arm64"
RESTRICT="mirror test"

RDEPEND="
	acct-user/mediadecay
	acct-group/mediadecay
	>=dev-python/flask-3.1.1[${PYTHON_USEDEP}]
	>=dev-python/sqlalchemy-2.0.50[${PYTHON_USEDEP}]
	>=dev-python/PlexAPI-4.15.16[${PYTHON_USEDEP}]
	>=dev-python/requests-2.32.3[${PYTHON_USEDEP}]
	>=dev-python/pyyaml-6.0.2[${PYTHON_USEDEP}]
	>=dev-python/ruamel-yaml-0.18[${PYTHON_USEDEP}]
	>=dev-python/bcrypt-4.2.1[${PYTHON_USEDEP}]
	>=dev-python/cheroot-11.1.2[${PYTHON_USEDEP}]
"

src_install() {
	distutils-r1_src_install

	newinitd "${FILESDIR}"/mediadecay.initd mediadecay
	newconfd "${FILESDIR}"/mediadecay.confd mediadecay
	systemd_dounit "${FILESDIR}"/mediadecay.service

	# Config lives under /etc; install the example as a reference.
	insinto /etc/mediadecay
	newins config.yaml.example config.yaml.example

	keepdir /var/lib/mediadecay
	fowners mediadecay:mediadecay /var/lib/mediadecay
	fperms 0750 /var/lib/mediadecay

	keepdir /var/log/mediadecay
	fowners mediadecay:mediadecay /var/log/mediadecay
	fperms 0750 /var/log/mediadecay

	keepdir /etc/mediadecay
	fowners root:mediadecay /etc/mediadecay
	fperms 0750 /etc/mediadecay
}

pkg_postinst() {
	elog "MediaDecay is now installed."
	elog ""
	elog "1. Create your configuration:"
	elog "     cp /etc/mediadecay/config.yaml.example /etc/mediadecay/config.yaml"
	elog "     \${EDITOR} /etc/mediadecay/config.yaml"
	elog "   Keep it readable only by the mediadecay group (contains secrets):"
	elog "     chown root:mediadecay /etc/mediadecay/config.yaml"
	elog "     chmod 0640 /etc/mediadecay/config.yaml"
	elog ""
	elog "2. Set the database path in config.yaml to the managed data dir:"
	elog "     database:"
	elog "       path: /var/lib/mediadecay/mediadecay.db"
	elog ""
	elog "3. Generate the web admin password hash:"
	elog "     python3 -c \"import bcrypt; print(bcrypt.hashpw(b'yourpass', bcrypt.gensalt()).decode())\""
	elog ""
	elog "4. Start the service (systemd):"
	elog "     systemctl enable --now mediadecay"
	elog "   or (OpenRC):"
	elog "     rc-update add mediadecay default && rc-service mediadecay start"
	elog ""
	elog "The service runs both the web UI and the daily scheduled maintenance."
	elog "Config:  /etc/mediadecay/config.yaml"
	elog "Data/DB: /var/lib/mediadecay/"
	elog "Logs:    /var/log/mediadecay/"
	elog ""
	elog "dev-python/PlexAPI is provided by this overlay. TLS is terminated"
	elog "in-process by cheroot when web.ssl_cert/web.ssl_key are set."
}
