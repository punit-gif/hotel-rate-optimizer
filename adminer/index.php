<?php
$server = getenv('ADMINER_DEFAULT_SERVER'); // e.g. "HOST:PORT"
if ($server) {
  header('Location: adminer.php?server=' . urlencode($server));
  exit;
}
require 'adminer.php';
