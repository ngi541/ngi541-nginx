#!/usr/bin/perl

use warnings;
use strict;

use Test::More;

BEGIN { use FindBin; chdir($FindBin::Bin); }

use lib 'lib';
use Test::Nginx;
use Test::Nginx::HTTP3;


my $t = Test::Nginx->new()
    ->has(qw/http http_v3 cryptx/)
    ->has_daemon('openssl')
    ->plan(4);


$t->write_file_expand('nginx.conf', <<'EOF_CONF');

%%TEST_GLOBALS%%

daemon off;

events {
}

http {
    %%TEST_GLOBALS_HTTP%%

    ssl_certificate_key localhost.key;
    ssl_certificate localhost.crt;

    server {
        listen 127.0.0.1:%%PORT_8980_UDP%% quic;
        server_name localhost;

        location / {
        }
    }
}

EOF_CONF


$t->write_file('openssl.conf', <<'EOF_SSL');
[ req ]
default_bits = 2048
encrypt_key = no
distinguished_name = req_distinguished_name

[ req_distinguished_name ]
EOF_SSL


my $d = $t->testdir();

system(
    'openssl req -x509 -new '
    . "-config $d/openssl.conf "
    . '-subj /CN=localhost/ '
    . "-out $d/localhost.crt "
    . "-keyout $d/localhost.key "
    . ">>$d/openssl.out 2>&1"
) == 0
    or die "failed to generate certificate: $!\n";


$t->run();


my $s = Test::Nginx::HTTP3->new();

ok(get($s), 'baseline HTTP/3 request');


#
# Build a completely valid 1-RTT protected PING packet first.
#
# encrypt_aead() performs both:
#
#   AES-GCM packet protection
#   QUIC header protection
#
my $bad = $s->encrypt_aead("\x01", 3);

my $bad_len = length($bad);


#
# Corrupt ONLY the last byte.
#
# With the one-byte PING payload, the protected payload is:
#
#   1 byte ciphertext || 16 byte GCM tag
#
# QUIC HP samples the first 16 protected bytes:
#
#   ciphertext byte || first 15 tag bytes
#
# Therefore the final byte is the 16th GCM-tag byte and is outside
# the HP sample.  Changing it preserves valid header protection but
# guarantees an invalid GCM authentication tag.
#
my $last = ord(substr($bad, -1, 1));

substr($bad, -1, 1) = chr($last ^ 0x01);


my $written = $s->{socket}->syswrite($bad);

is($written, $bad_len, 'tampered QUIC packet sent');


#
# The bad packet must be discarded without killing the QUIC
# connection.  A subsequent authenticated request must still work.
#
ok(get($s), 'connection remains usable after bad authentication tag');


#
# Our NGI541 adapter logs this marker only for
# NGI541_STATUS_AUTH_FAILED.
#
like(
    $t->read_file('error.log'),
    qr/quic NGI541 packet authentication failed/,
    'NGI541 AES-GCM authentication failure observed'
);


###############################################################################


sub get {
    my ($s) = @_;

    my $frames = $s->read(
        all => [
            {
                sid => $s->new_stream(),
                fin => 1
            }
        ]
    );

    return grep {
        $_->{type} eq 'HEADERS'
    } @$frames;
}


###############################################################################
